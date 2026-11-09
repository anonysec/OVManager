// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package main

import (
	"io/fs"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/panel"
)

type countingFS struct {
	fs.FS
	stats atomic.Int32
}

func (c *countingFS) Stat(name string) (fs.FileInfo, error) {
	c.stats.Add(1)
	return fs.Stat(c.FS, name)
}
func (c *countingFS) ReadFile(name string) ([]byte, error) {
	return fs.ReadFile(c.FS, name)
}
func (c *countingFS) Open(name string) (fs.File, error) { return c.FS.Open(name) }

func TestSPACachesIndexAndFileServer(t *testing.T) {
	dir := t.TempDir()
	dist := filepath.Join(dir, "web", "dist")
	if err := os.MkdirAll(dist, 0o755); err != nil {
		t.Fatal(err)
	}
	idx := "<html><head></head><body><script>hi</script></body></html>"
	if err := os.WriteFile(filepath.Join(dist, "index.html"), []byte(idx), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("OVM_APP_DIR", dir)
	dataDir := t.TempDir()
	t.Setenv("DATA_DIR", dataDir)
	conn, err := db.Open(filepath.Join(dataDir, "panel.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE settings (id INTEGER PRIMARY KEY, url_path TEXT); INSERT INTO settings (id, url_path) VALUES (1, '');`); err != nil {
		t.Fatal(err)
	}
	h := panel.NewHandler(auth.NewService(conn, dataDir))
	spa := spaHandler(h)
	r1 := httptest.NewRequest(http.MethodGet, "http://x/index.html", nil)
	w1 := httptest.NewRecorder()
	spa.ServeHTTP(w1, r1)
	if w1.Code != http.StatusOK {
		t.Fatalf("first index = %d", w1.Code)
	}
	r2 := httptest.NewRequest(http.MethodGet, "http://x/index.html", nil)
	w2 := httptest.NewRecorder()
	spa.ServeHTTP(w2, r2)
	if w2.Code != http.StatusOK {
		t.Fatalf("second index = %d", w2.Code)
	}
	if !strings.Contains(w2.Body.String(), "<base") {
		t.Fatal("base not injected")
	}
}

func TestSPACachedIndexAvoidsStat(t *testing.T) {
	dir := t.TempDir()
	dist := filepath.Join(dir, "web", "dist")
	if err := os.MkdirAll(dist, 0o755); err != nil {
		t.Fatal(err)
	}
	idx := "<html><head></head><body>hi</body></html>"
	if err := os.WriteFile(filepath.Join(dist, "index.html"), []byte(idx), 0o644); err != nil {
		t.Fatal(err)
	}
	dataDir := t.TempDir()
	conn, err := db.Open(filepath.Join(dataDir, "panel.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE settings (id INTEGER PRIMARY KEY, url_path TEXT); INSERT INTO settings (id, url_path) VALUES (1, '');`); err != nil {
		t.Fatal(err)
	}
	h := panel.NewHandler(auth.NewService(conn, dataDir))
	cfs := &countingFS{FS: os.DirFS(dist)}
	spa := spaHandlerWithFS(h, cfs)
	before := cfs.stats.Load()
	for i := 0; i < 2; i++ {
		r := httptest.NewRequest(http.MethodGet, "http://x/index.html", nil)
		w := httptest.NewRecorder()
		spa.ServeHTTP(w, r)
		if w.Code != http.StatusOK {
			t.Fatalf("index %d = %d", i, w.Code)
		}
	}
	if cfs.stats.Load() != before {
		t.Fatalf("index requests stat'd dist: before=%d after=%d", before, cfs.stats.Load())
	}
}
