// Package db opens the shared SQLite database.
//
// Pragmas mirror backend/db/engine.py (WAL, NORMAL sync, 30s busy timeout,
// foreign keys on). They ride in the DSN so every pooled connection gets them.
package db

import (
	"database/sql"
	"fmt"
	"os"

	_ "modernc.org/sqlite" // pure-Go driver, no cgo
)

// DefaultPath is the panel database location (DATA_DIR overrides at call site).
const DefaultPath = "data/ovmanager.db"

// dsnPragmas keeps the engine's PRAGMAs. cache_size -32768 = 32MiB.
//
// ponytail: perf.low_resource (8MiB cache on 1GB boxes) not wired — pass a
// variant DSN when the setting gains a reader here.
const dsnPragmas = "?_pragma=journal_mode(WAL)" +
	"&_pragma=synchronous(NORMAL)" +
	"&_pragma=busy_timeout(30000)" +
	"&_pragma=foreign_keys(ON)" +
	"&_pragma=temp_store(MEMORY)" +
	"&_pragma=cache_size(-32768)" +
	"&_pragma=mmap_size(268435456)"

// Open opens path, creating the file if missing.
func Open(path string) (*sql.DB, error) {
	conn, err := sql.Open("sqlite", "file:"+path+dsnPragmas)
	if err != nil {
		return nil, fmt.Errorf("open sqlite %s: %w", path, err)
	}
	if err := conn.Ping(); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("ping sqlite %s: %w", path, err)
	}
	_ = os.Chmod(path, 0o600)
	return conn, nil
}
