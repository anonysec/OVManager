// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"crypto/tls"
	"os"
	"sync"
	"time"
)

// ReloadingCertificate returns a GetCertificate callback that reloads the
// pair when either file changes. The panel starts TLS once; a renewal written
// by the ACME worker is served on the next handshake without a restart.
func ReloadingCertificate(certFile, keyFile string) func(*tls.ClientHelloInfo) (*tls.Certificate, error) {
	var mu sync.Mutex
	var cached *tls.Certificate
	var certMod, keyMod time.Time
	return func(*tls.ClientHelloInfo) (*tls.Certificate, error) {
		mu.Lock()
		defer mu.Unlock()
		certInfo, err := os.Stat(certFile)
		if err != nil {
			return nil, err
		}
		keyInfo, err := os.Stat(keyFile)
		if err != nil {
			return nil, err
		}
		if cached == nil || !certInfo.ModTime().Equal(certMod) || !keyInfo.ModTime().Equal(keyMod) {
			pair, err := tls.LoadX509KeyPair(certFile, keyFile)
			if err != nil {
				return nil, err
			}
			cached = &pair
			certMod, keyMod = certInfo.ModTime(), keyInfo.ModTime()
		}
		return cached, nil
	}
}
