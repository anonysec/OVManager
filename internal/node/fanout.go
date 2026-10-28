// Fan-out bounds shared by every node RPC site (backend).
package node

import (
	"sync"
	"time"
)

// Fanout limits and deadline mirror backend/node/fanout.py.
const (
	NodeFanoutLimit       = 20
	BackgroundFanoutLimit = 4
	RequestFanoutDeadline = 10 * time.Second
)

// ChunkBySize splits items into chunks of at most batchSize items and maxBytes
// total. A single item over maxBytes still forms its own chunk.
func ChunkBySize[T any](items []T, batchSize, maxBytes int, itemBytes func(T) int) [][]T {
	chunks := [][]T{}
	current := []T{}
	currentBytes := 0
	for _, item := range items {
		size := itemBytes(item)
		if len(current) > 0 && (len(current) >= batchSize || currentBytes+size > maxBytes) {
			chunks = append(chunks, current)
			current = []T{}
			currentBytes = 0
		}
		current = append(current, item)
		currentBytes += size
	}
	if len(current) > 0 {
		chunks = append(chunks, current)
	}
	return chunks
}

var (
	// semMu guards nodeSem: a test swaps it, and a swap that raced with a
	// running call would release the slot into a different channel.
	semMu   sync.RWMutex
	nodeSem = make(chan struct{}, NodeFanoutLimit)
)

// currentSem returns the live semaphore. Its capacity IS the concurrency cap.
func currentSem() chan struct{} {
	semMu.RLock()
	defer semMu.RUnlock()
	return nodeSem
}

// fanoutLimit is the live concurrency cap.
func fanoutLimit() int { return cap(currentSem()) }

// setFanoutLimit shrinks the shared concurrency cap for a test and returns a
// restore function. Production always uses NodeFanoutLimit.
func setFanoutLimit(n int) func() {
	if n < 1 {
		n = 1
	}
	semMu.Lock()
	old := nodeSem
	nodeSem = make(chan struct{}, n)
	semMu.Unlock()
	return func() {
		semMu.Lock()
		nodeSem = old
		semMu.Unlock()
	}
}

// FairShareTimeout is the per-call timeout for a fan-out of `calls` under
// `limit` concurrency.
//
// A call that hangs holds its concurrency slot for its whole timeout, so a
// fleet larger than the limit starves the calls queued behind it: with 20
// slots and 25 nodes, 20 black-holed nodes would hold every slot for their
// own timeout, the 5 healthy ones would never start, and the panel would
// report EVERY node as dead.
//
// The batch needs ceil(calls/limit) rounds, so each round gets an equal share
// of the deadline. A fleet that fits within the limit keeps its own
// timeouts.
func FairShareTimeout(deadline time.Duration, calls, limit int) time.Duration {
	if limit <= 0 || calls <= limit {
		return deadline
	}
	rounds := (calls + limit - 1) / limit
	share := deadline / time.Duration(rounds)
	if share <= 0 {
		share = time.Second
	}
	return share
}

// RunBounded runs one blocking node call under the shared cap.
func RunBounded(fn func() any) any {
	// The semaphore is captured once: the acquire and the release must use
	// the same channel, or a swap in between would leak the slot.
	sem := currentSem()
	sem <- struct{}{}
	defer func() { <-sem }()
	return fn()
}

// GatherBounded runs calls concurrently under the shared cap and returns one
// result per call in order; a panic becomes an error (return_exceptions=True).
func GatherBounded(calls []func() any) []any {
	results := make([]any, len(calls))
	var wg sync.WaitGroup
	for i, call := range calls {
		wg.Add(1)
		go func(i int, call func() any) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results[i] = asError(r)
				}
			}()
			results[i] = RunBounded(call)
		}(i, call)
	}
	wg.Wait()
	return results
}

// FanoutDeadline is returned for a node that did not answer before the
// request's fan-out deadline — an error so callers' guards handle it.
type FanoutDeadline struct{ Msg string }

func (e FanoutDeadline) Error() string { return e.Msg }

// GatherNodes runs a fan-out under the shared cap, bounded in total time.
// Unfinished calls are represented as a FanoutDeadline (and not cancelled).
func GatherNodes(calls []func() any, deadline time.Duration) []any {
	if len(calls) == 0 {
		return []any{}
	}
	results := make([]any, len(calls))
	var mu sync.Mutex
	done := make(chan int, len(calls))
	for i, call := range calls {
		go func(i int, call func() any) {
			defer func() {
				if r := recover(); r != nil {
					mu.Lock()
					results[i] = asError(r)
					mu.Unlock()
				}
				done <- i
			}()
			val := RunBounded(call)
			mu.Lock()
			results[i] = val
			mu.Unlock()
		}(i, call)
	}
	timer := time.NewTimer(deadline)
	defer timer.Stop()
	for n := 0; n < len(calls); n++ {
		select {
		case <-done:
		case <-timer.C:
			mu.Lock()
			for j := range results {
				if results[j] == nil {
					results[j] = FanoutDeadline{Msg: "no answer within the fan-out deadline"}
				}
			}
			out := append([]any(nil), results...)
			mu.Unlock()
			return out
		}
	}
	return results
}

type errString string

func (e errString) Error() string { return string(e) }

func asError(v any) error {
	if err, ok := v.(error); ok {
		return err
	}
	return errString(toString(v))
}

func toString(v any) string {
	if v == nil {
		return "panic"
	}
	if s, ok := v.(string); ok {
		return s
	}
	return "panic"
}
