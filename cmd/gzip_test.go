// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package main

import (
	"net/http/httptest"
	"testing"
	"testing/fstest"
)

func TestServePrecompressedUsesTheGzipSibling(t *testing.T) {
	fsys := fstest.MapFS{
		"assets/app.js":    {Data: []byte("plain")},
		"assets/app.js.gz": {Data: []byte("compressed")},
	}
	req := httptest.NewRequest("GET", "/assets/app.js", nil)
	req.Header.Set("Accept-Encoding", "gzip")
	rec := httptest.NewRecorder()
	if !servePrecompressed(rec, req, fsys, "assets/app.js") {
		t.Fatal("expected the .gz sibling to be served")
	}
	if got := rec.Header().Get("Content-Encoding"); got != "gzip" {
		t.Fatalf("Content-Encoding = %q", got)
	}
	if got := rec.Header().Get("Vary"); got != "Accept-Encoding" {
		t.Fatalf("Vary = %q", got)
	}
	if rec.Body.String() != "compressed" {
		t.Fatalf("body = %q", rec.Body.String())
	}
}

func TestServePrecompressedFallsBackWithoutGzipOrSibling(t *testing.T) {
	fsys := fstest.MapFS{"assets/app.js": {Data: []byte("plain")}}
	req := httptest.NewRequest("GET", "/assets/app.js", nil)
	rec := httptest.NewRecorder()
	if servePrecompressed(rec, req, fsys, "assets/app.js") {
		t.Fatal("must not compress without Accept-Encoding: gzip")
	}
	req.Header.Set("Accept-Encoding", "gzip")
	if servePrecompressed(rec, req, fsys, "assets/app.js") {
		t.Fatal("must fall back when no .gz sibling exists")
	}
}
