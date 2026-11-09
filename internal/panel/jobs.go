// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"context"
	"log"
	"runtime/debug"
	"time"
)

type job struct {
	name  string
	every func() time.Duration
	delay time.Duration
	fn    func(context.Context)
}

// Run executes each job on its own timer. The first tick fires after
// delay, then every interval returned by every (re-read per tick, so
// interval changes apply without restart). The loop stops on ctx.Done.
// A panic in fn is logged with its stack and the job continues.
func Run(ctx context.Context, jobs []job) {
	for _, j := range jobs {
		go runJob(ctx, j)
	}
}

func runJob(ctx context.Context, j job) {
	if j.delay > 0 {
		select {
		case <-time.After(j.delay):
		case <-ctx.Done():
			return
		}
	}
	tick := func() {
		running := make(chan struct{}, 1)
		select {
		case running <- struct{}{}:
		default:
			log.Printf("%s: previous run still active, skipping tick", j.name)
			return
		}
		go func() {
			defer func() { <-running }()
			defer func() {
				if r := recover(); r != nil {
					log.Printf("%s panic: %v\n%s", j.name, r, debug.Stack())
				}
			}()
			j.fn(ctx)
		}()
	}
	tick()
	interval := j.every()
	if interval <= 0 {
		interval = time.Minute
	}
	timer := time.NewTimer(interval)
	for {
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
			tick()
			interval = j.every()
			if interval <= 0 {
				interval = time.Minute
			}
			timer.Reset(interval)
		}
	}
}
