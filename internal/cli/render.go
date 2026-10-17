// Package render reproduces scripts/lib/render.sh (and cli/render.py) byte for
// byte: three spaces, a 14-wide label field, one space, then the value.
package cli

import (
	"os"
	"strings"
)

const (
	labelW = 14
	indent = "   "
)

// unicodeOK mirrors render.py: Unicode only where the locale can show it.
func unicodeOK() bool {
	for _, key := range []string{"LC_ALL", "LC_CTYPE", "LANG"} {
		if strings.Contains(strings.ToLower(os.Getenv(key)), "utf") {
			return true
		}
	}
	return false
}

// glyphs returns (done, failed).
func glyphs() (string, string) {
	if unicodeOK() {
		return "✓", "✗"
	}
	return "ok", "XX"
}

func kv(label, value string) string {
	w := labelW
	if len(label) > w {
		w = len(label)
	}
	return indent + pad(label, w) + " " + value
}

func pad(s string, w int) string {
	if len(s) >= w {
		return s
	}
	return s + strings.Repeat(" ", w-len(s))
}

func rowsWidth(items [][2]string) int {
	w := labelW
	for _, it := range items {
		if len(it[0]) > w {
			w = len(it[0])
		}
	}
	return w
}

func renderRows(items [][2]string) []string {
	w := rowsWidth(items)
	out := make([]string, 0, len(items))
	for _, it := range items {
		out = append(out, indent+pad(it[0], w)+" "+it[1])
	}
	return out
}

func heading(text string) string { return "  " + text }

func okLine(message string) string {
	done, _ := glyphs()
	return "  " + done + " " + message
}

func failedLine(message string) string {
	_, bad := glyphs()
	return "  " + bad + " " + message
}

func hint(message string) string { return "    " + message }

func block(lines []string) string { return strings.Join(lines, "\n") + "\n" }
