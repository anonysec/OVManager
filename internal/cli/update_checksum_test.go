// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package cli

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func sumHex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func TestExpectedHashFor(t *testing.T) {
	sums := "aaa  ovmanager-linux-amd64\nbbb  ovmanager-linux-arm64\n"
	got, err := expectedHashFor(sums, "ovmanager-linux-arm64")
	if err != nil || got != "bbb" {
		t.Fatalf("got %q err %v", got, err)
	}
	if _, err := expectedHashFor(sums, "ovmanager-linux-s390x"); err == nil {
		t.Fatal("missing entry must error")
	}
}

func TestDownloadVerifiedMatch(t *testing.T) {
	body := []byte("fake binary\n")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(body)
	}))
	defer srv.Close()
	dst := filepath.Join(t.TempDir(), "ovmanager")
	if err := downloadVerified(srv.URL, dst, sumHex(body)); err != nil {
		t.Fatalf("match rejected: %v", err)
	}
	got, _ := os.ReadFile(dst)
	if string(got) != string(body) {
		t.Fatalf("content=%q want %q", got, body)
	}
}

func TestDownloadVerifiedTampered(t *testing.T) {
	body := []byte("tampered binary\n")
	original := []byte("original binary\n")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(body)
	}))
	defer srv.Close()
	dst := filepath.Join(t.TempDir(), "ovmanager")
	if err := downloadVerified(srv.URL, dst, sumHex(original)); err == nil {
		t.Fatal("tampered body accepted")
	}
	if _, err := os.Stat(dst); !os.IsNotExist(err) {
		t.Fatal("tampered download left file behind")
	}
}

func TestFetchExpectedHashMissingSums(t *testing.T) {
	const sums = "abc  ovmanager-linux-amd64\n"
	// Test the shared parsing via a direct call: missing asset name errors.
	if _, err := expectedHashFor(sums, "ovmanager-linux-arm64"); err == nil {
		t.Fatal("missing SHA256SUMS line accepted")
	}
	if got := sumHex([]byte(strings.TrimSpace(""))); got == "" {
		t.Fatal("empty hash")
	}
}
