package notify

import (
	"log"
	"runtime/debug"
)

// runGuarded runs fn and swallows a panic, logging it with a stack.
//
// The worker goroutine is started under a sync.Once, so a panic that unwinds
// it stops notifications for the life of the process and nothing restarts it.
// Guarding each tick keeps the worker alive and makes the failure visible.
func runGuarded(what string, fn func()) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("%s panic: %v\n%s", what, r, debug.Stack())
		}
	}()
	fn()
}
