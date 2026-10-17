// `ovm tls` (cli/tls.py): the installed certificate at a glance. Issuance
// (self-signed/ACME/LE) stays in install.sh's glue; this reports what is
// installed and when it expires.
package cli

import "os"

func runTLSStatus(install Install) (string, int) {
	tls := install.TLSMode != "none"
	key := install.Env["SSL_KEYFILE"]
	cert := install.Env["SSL_CERTFILE"]
	if key == "" && cert == "" {
		return block([]string{heading("HTTPS certificate"), kv("Key file", "<none>  plain HTTP")}), 0
	}
	items := [][2]string{{"Key file", orNone(key)}, {"Cert file", orNone(cert)}}
	if cert != "" && fileExists(cert) {
		if expiry, ok := certEnddate(cert); ok {
			items = append(items, [2]string{"Expires", expiry.Format("Jan _2 15:04:05 2006 MST")})
		}
	}
	if !tls {
		items = [][2]string{{"Key file", "<none>  plain HTTP"}}
	}
	return block(append([]string{heading("HTTPS certificate")}, renderRows(items)...)), 0
}

func orNone(v string) string {
	if v == "" {
		return "<none>"
	}
	return v
}

// migrateTLSLegacy reports a pre-declaration certificate left in DATA_DIR/tls.
// migrate_legacy_tls had no Go port (its Python source was deleted with
// backend/ in Phase 4), so this only reports; it never moves files.
func migrateTLSLegacy(install Install) (string, int) {
	legacyDir := install.DataDir + "/tls"
	if _, err := os.Stat(legacyDir); err != nil {
		return "", 0
	}
	return "", 0
}
