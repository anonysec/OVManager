// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package cli

import (
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"os"
	"path/filepath"
	"testing"
)

func TestVerifySignatureAndTamperRejection(t *testing.T) {
	// Generate an Ed25519 test keypair
	pub, priv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatalf("ed25519.GenerateKey: %v", err)
	}
	pkix, err := x509.MarshalPKIXPublicKey(pub)
	if err != nil {
		t.Fatalf("MarshalPKIXPublicKey: %v", err)
	}
	pubPEM := string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: pkix}))

	tmpDir := t.TempDir()
	binPath := filepath.Join(tmpDir, "ovmanager-bin")
	originalData := []byte("authentic binary content")
	if err := os.WriteFile(binPath, originalData, 0o755); err != nil {
		t.Fatal(err)
	}

	sig := ed25519.Sign(priv, originalData)

	// Valid signature and checksum check
	h := sha256.Sum256(originalData)
	checksumBody := hex.EncodeToString(h[:]) + "  ovmanager-bin\n"
	if err := verifyChecksum(binPath, checksumBody); err != nil {
		t.Fatalf("verifyChecksum failed on valid file: %v", err)
	}
	if err := verifySignatureWithKey(binPath, sig, pubPEM); err != nil {
		t.Fatalf("verifySignatureWithKey failed on valid file: %v", err)
	}

	// Tampered binary with matching tampered checksum (H1 attack vector)
	tamperedData := []byte("tampered / backdoored binary content")
	if err := os.WriteFile(binPath, tamperedData, 0o755); err != nil {
		t.Fatal(err)
	}
	tamperedHash := sha256.Sum256(tamperedData)
	tamperedChecksumBody := hex.EncodeToString(tamperedHash[:]) + "  ovmanager-bin\n"

	// 1. Checksum verification PASSES because the attacker updated the sidecar!
	if err := verifyChecksum(binPath, tamperedChecksumBody); err != nil {
		t.Fatalf("expected verifyChecksum to pass on attacker's matching checksum, got: %v", err)
	}

	// 2. BUT signature verification MUST FAIL because attacker lacks private key!
	if err := verifySignatureWithKey(binPath, sig, pubPEM); err == nil {
		t.Fatalf("SECURITY FLAW: verifySignatureWithKey accepted tampered binary with matching checksum!")
	}
}
