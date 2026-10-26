package panel

import (
	"log"
	"runtime/debug"
)

// runGuarded runs fn and swallows a panic, logging it with a stack.
//
// A background worker is started under a sync.Once, so a panic that unwinds
// its goroutine stops it for the life of the process and nothing restarts it.
// The traffic worker is the only thing that counts bytes: when it dies,
// users.used freezes while real traffic keeps flowing, and the only symptom
// is a log line that stops appearing. Guarding each tick keeps the worker
// alive and makes the failure visible.
func runGuarded(what string, fn func()) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("%s panic: %v\n%s", what, r, debug.Stack())
		}
	}()
	fn()
}
