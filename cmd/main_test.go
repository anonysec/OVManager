// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// Regression: blankWriter swallowed /api/* 404 JSON bodies when
// StripPrefix stripped before path capture. The API contract requires the
// body to reach the frontend. Non-API 404s must stay void blank.
func TestBlankWriterAPI404BodyPresent(t *testing.T) {
	api := http.NewServeMux()
	api.HandleFunc("GET /nonexistent", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"missing"}`))
	})
	root := http.NewServeMux()
	root.Handle("/api/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		orig := r.URL.Path
		http.StripPrefix("/api", blankHandler{Handler: api, Path: orig}).ServeHTTP(w, r)
	}))
	req := httptest.NewRequest(http.MethodGet, "http://x/api/nonexistent", nil)
	rec := httptest.NewRecorder()
	root.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status %d, want 404", rec.Code)
	}
	body := rec.Body.String()
	if !strings.Contains(body, "missing") {
		t.Fatalf("API 404 body blanked, got %q want JSON detail", body)
	}
}

func TestBlankWriterNonAPI404Blank(t *testing.T) {
	root := http.NewServeMux()
	root.Handle("/api/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		orig := r.URL.Path
		http.StripPrefix("/api", blankHandler{Handler: http.NewServeMux(), Path: orig}).ServeHTTP(w, r)
	}))
	// /apix is not an API path — body must stay void.
	req := httptest.NewRequest(http.MethodGet, "http://x/apix", nil)
	rec := httptest.NewRecorder()
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	blankHandler{Handler: h, Path: "/apix"}.ServeHTTP(rec, req)
	if rec.Body.String() != "" {
		t.Fatalf("non-API 404 body = %q, want blank", rec.Body.String())
	}
	// /api/ exact must preserve body.
	rec2 := httptest.NewRecorder()
	h2 := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"x"}`))
	})
	blankHandler{Handler: h2, Path: "/api/"}.ServeHTTP(rec2, req)
	if !strings.Contains(rec2.Body.String(), "x") {
		t.Fatalf("/api/ body blanked, got %q", rec2.Body.String())
	}
}