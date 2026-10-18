package main

import "testing"

func TestServeMode(t *testing.T) {
	cases := []struct {
		tls  bool
		port string
		addr string
		use  bool
	}{
		{false, "2095", "127.0.0.1:2095", false},
		{true, "2095", "0.0.0.0:2095", true},
		{false, "8080", "127.0.0.1:8080", false},
		{true, "8080", "0.0.0.0:8080", true},
	}
	for _, c := range cases {
		addr, use := serveMode(c.tls, c.port)
		if addr != c.addr || use != c.use {
			t.Errorf("serveMode(%v,%s) = (%s,%v), want (%s,%v)", c.tls, c.port, addr, use, c.addr, c.use)
		}
	}
	// invariant: no plaintext on 0.0.0.0
	if a, _ := serveMode(false, "2095"); a == "0.0.0.0:2095" {
		t.Fatal("plaintext bound to 0.0.0.0")
	}
}
