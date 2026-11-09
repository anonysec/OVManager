// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAPIUnknownRouteEmpty404(t *testing.T) {
	api := http.NewServeMux()
	api.HandleFunc("GET /login", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})
	api.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", api))
	root.Handle("/api", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	req := httptest.NewRequest(http.MethodGet, "http://x/api/nonexistent", nil)
	rec := httptest.NewRecorder()
	root.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status %d, want 404", rec.Code)
	}
	if rec.Body.Len() != 0 {
		t.Fatalf("API 404 body = %q, want empty", rec.Body.String())
	}
}

func TestAPIExactEmpty404(t *testing.T) {
	root := http.NewServeMux()
	root.Handle("/api", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	req := httptest.NewRequest(http.MethodGet, "http://x/api", nil)
	rec := httptest.NewRecorder()
	root.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound || rec.Body.Len() != 0 {
		t.Fatalf("/api = %d %q, want 404 empty", rec.Code, rec.Body.String())
	}
}
