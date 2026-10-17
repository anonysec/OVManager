// Fan-out bounds shared by every node RPC site (backend/node/fanout.py).
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

var nodeSem = make(chan struct{}, NodeFanoutLimit)

// RunBounded runs one blocking node call under the shared cap.
func RunBounded(fn func() any) any {
	nodeSem <- struct{}{}
	defer func() { <-nodeSem }()
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
			mu.Unlock()
			return results
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
