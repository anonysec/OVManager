// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import "testing"

func TestMalformedPinFailsClosed(t *testing.T) {
	pin := "-----BEGIN CERTIFICATE-----\nnot base64!!!\n-----END CERTIFICATE-----"
	c, err := NewClient("127.0.0.1", 1, "k", pin, "", 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.cachedTransport(); err == nil {
		t.Fatal("malformed pinned certificate produced a usable transport")
	}
}
