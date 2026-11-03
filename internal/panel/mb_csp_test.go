package panel

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

type failingReader struct{}

func (failingReader) Read(p []byte) (int, error) {
	return 0, errors.New("rng failure")
}

func TestGenerateNonceFailsClosed(t *testing.T) {
	old := randReader
	randReader = failingReader{}
	t.Cleanup(func() { randReader = old })
	if _, err := generateNonce(); err == nil {
		t.Fatal("expected error on RNG failure")
	}
}

func TestSecurityHeadersFailsOnRNGFailure(t *testing.T) {
	old := randReader
	randReader = failingReader{}
	t.Cleanup(func() { randReader = old })
	h := securityHeaders(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", rr.Code)
	}
	if bytes.Contains(rr.Body.Bytes(), []byte("static-csp-nonce")) {
		t.Fatal("static nonce leaked")
	}
	_ = io.Discard
}
