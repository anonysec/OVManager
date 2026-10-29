package node

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

// ResetForTests clears the registry and health state.
func resetForTests() {
	connMu.Lock()
	defer connMu.Unlock()
	connections = map[int64]*connection{}
}
