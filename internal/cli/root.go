// `ovmanager` cobra root: one binary that is both the panel and the operator CLI
// (Phase 5). Global flags are accepted before or after the subcommand.
package cli

import (
	"bufio"
	"crypto/tls"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

type app struct {
	out          io.Writer
	exit         int
	installDir   string
	dataDir      string
	inContainer  bool
	serviceState string
	publicIP     string
	showAll      bool
}

// Run executes the CLI with args (excluding argv[0]) and returns the exit code.
func Run(args []string, out io.Writer) int {
	a := &app{out: out}
	root := a.rootCmd()
	root.SetArgs(args)
	root.SetOut(out)
	root.SetErr(out)
	if err := root.Execute(); err != nil {
		return 2
	}
	return a.exit
}

func (a *app) install() Install {
	return DetectInstall(a.installDir, a.dataDir)
}

func (a *app) rootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:           "ovmanager",
		Short:         "OVManager local operator CLI",
		SilenceUsage:  true,
		SilenceErrors: false,
		Run: func(cmd *cobra.Command, args []string) {
			if len(args) > 0 {
				return
			}
			fi, _ := os.Stdin.Stat()
			if fi == nil || (fi.Mode()&os.ModeCharDevice) == 0 {
				_ = cmd.Help()
				return
			}
			runInteractiveMenu(a, cmd)
		},
	}
	pf := root.PersistentFlags()
	pf.StringVar(&a.installDir, "install-dir", "", "override install dir (default: $OVM_APP_DIR or /opt/ovmanager)")
	pf.StringVar(&a.dataDir, "data-dir", "", "override data dir")
	pf.BoolVar(&a.inContainer, "in-container", false, "running inside the panel container (set by ovmanager)")
	pf.StringVar(&a.serviceState, "service-state", "", "service state reported by the host (running/stopped/unknown)")
	pf.StringVar(&a.publicIP, "public-ip", "", "the host's primary IP")
	pf.BoolVarP(&a.showAll, "all", "a", false, "show all fields")

	root.AddCommand(
		a.statusCmd(), a.logsCmd(), a.doctorCmd(), a.backupCmd(), a.restoreCmd(),
		a.tlsCmd(), a.urlpathCmd(), a.resetPasswordCmd(), a.updateCmd(), a.serviceCmd(),
		a.healthCmd(), a.authCmd(),
	)
	return root
}

func (a *app) emit(text string, code int) {
	fmt.Fprint(a.out, text)
	a.exit = code
}

func (a *app) statusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "service, health, version, URL",
		RunE: func(_ *cobra.Command, _ []string) error {
			data := collectStatus(a.install(), a.serviceState, a.publicIP)
			code := 1
			if data.ok {
				code = 0
			}
			a.emit(renderStatus(data, a.showAll), code)
			return nil
		},
	}
}

func (a *app) healthCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "health",
		Short: "probe the local panel /health endpoint",
		RunE: func(_ *cobra.Command, _ []string) error {
			port := os.Getenv("PORT")
			if port == "" {
				port = "2095"
			}
			// Plain probe first (the common case); fall back to HTTPS for a
			// TLS-only panel, accepting a self-signed/loopback cert.
			resp, err := http.Get("http://127.0.0.1:" + port + "/health") // #nosec // localhost health probe
			if err == nil && resp != nil && resp.StatusCode == http.StatusOK {
				_ = resp.Body.Close()
				a.emit("ok\n", 0)
				return nil
			}
			if resp != nil {
				_ = resp.Body.Close()
			}
			client := &http.Client{
				Timeout:   5 * time.Second,
				Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}, // #nosec G402 // local self-signed fallback
			}
			resp, err = client.Get("https://127.0.0.1:" + port + "/health") // #nosec // localhost health probe
			if err != nil || resp == nil || resp.StatusCode != http.StatusOK {
				if resp != nil {
					_ = resp.Body.Close()
				}
				a.emit("unhealthy\n", 1)
				return nil
			}
			_ = resp.Body.Close()
			a.emit("ok\n", 0)
			return nil
		},
	}
}

func (a *app) logsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "logs [count|-f]",
		Short: "tail service logs",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			arg := "100"
			if len(args) == 1 && args[0] != "" {
				arg = args[0]
			}
			a.exit = runLogs(buildLogsCommand(a.install().ComposeFile(), arg))
			return nil
		},
	}
}

func (a *app) doctorCmd() *cobra.Command {
	var fix bool
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "read-only health checks",
		RunE: func(_ *cobra.Command, _ []string) error {
			inst := a.install()
			checks := collectDoctor(inst, a.serviceState, a.inContainer)
			if fix {
				checks = fixAll(inst, a.serviceState, a.inContainer)
			}
			code := 0
			for _, c := range checks {
				if !c.OK {
					code = 1
				}
			}
			a.emit(renderDoctor(checks, a.showAll), code)
			return nil
		},
	}
	cmd.Flags().BoolVar(&fix, "fix", false, "auto-fix service/autostart/perms")
	return cmd
}

func (a *app) backupCmd() *cobra.Command {
	var keep string
	cmd := &cobra.Command{
		Use:   "backup",
		Short: "save a data backup now",
		RunE: func(_ *cobra.Command, _ []string) error {
			text, code := runBackup(a.install(), keep)
			a.emit(text, code)
			return nil
		},
	}
	cmd.Flags().StringVar(&keep, "keep", "", "tarballs to keep (1-500, default 14)")
	return cmd
}

func (a *app) restoreCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "restore [name]",
		Short: "list backups, or restore one by name",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			name := ""
			if len(args) == 1 {
				name = args[0]
			}
			text, code := runRestore(a.install(), name)
			a.emit(text, code)
			return nil
		},
	}
}

func (a *app) tlsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:     "tls [status|issue|selfsigned|install|remove|renew]",
		Aliases: []string{"ssl", "cert"},
		Short:   "HTTPS certificate management (interactive menu)",
		Args:    cobra.ArbitraryArgs,
		RunE: func(_ *cobra.Command, args []string) error {
			inst := a.install()
			// Interactive menu on a TTY with no args.
			if len(args) == 0 {
				isTTY := false
				if fi, _ := os.Stdin.Stat(); fi != nil && (fi.Mode()&os.ModeCharDevice) != 0 {
					isTTY = true
				}
				if !isTTY {
					if f, err := os.Open("/dev/tty"); err == nil {
						_ = f.Close()
						isTTY = true
					}
				}
				if isTTY {
					runTLSMenu(a, inst)
					return nil
				}
				text, code := runTLSStatus(inst)
				a.emit(text, code)
				return nil
			}
			switch {
			case args[0] == "status":
				text, code := runTLSStatus(inst)
				a.emit(text, code)
			case args[0] == "remove":
				text, code := runTLSRemove(inst)
				a.emit(text, code)
			case args[0] == "selfsigned":
				domain := ""
				if len(args) > 1 {
					domain = args[1]
				}
				text, code := runTLSSelfSigned(inst, domain)
				a.emit(text, code)
			case args[0] == "install":
				if len(args) < 3 {
					a.emit("usage: ovmanager tls install <cert.pem> <key.pem>\n", 2)
					return nil
				}
				text, code := runTLSInstall(inst, args[1], args[2])
				a.emit(text, code)
			case args[0] == "renew":
				text, code := runTLSRenew(inst)
				a.emit(text, code)
			case args[0] == "issue" || args[0] == "acme":
				if len(args) < 2 {
					a.emit("usage: ovmanager tls issue <domain-or-ip> [email]\n", 2)
					return nil
				}
				email := ""
				if len(args) > 2 {
					email = args[2]
				}
				text, code := runTLSAcme(inst, args[1], email)
				a.emit(text, code)
			default:
				// treat as domain/IP → issue Let's Encrypt cert
				email := ""
				if len(args) > 1 {
					email = args[1]
				}
				text, code := runTLSAcme(inst, args[0], email)
				a.emit(text, code)
			}
			return nil
		},
	}
	return cmd
}
func (a *app) urlpathCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "urlpath",
		Short: "print the url prefix the panel is serving",
		RunE: func(_ *cobra.Command, _ []string) error {
			text, code := runURLPathShow(a.install())
			a.emit(text, code)
			return nil
		},
	}
	cmd.AddCommand(
		&cobra.Command{
			Use:   "show",
			Short: "print the url prefix the panel is serving",
			RunE: func(_ *cobra.Command, _ []string) error {
				text, code := runURLPathShow(a.install())
				a.emit(text, code)
				return nil
			},
		},
		&cobra.Command{
			Use:   "set [prefix]",
			Short: "set the url prefix",
			Args:  cobra.MaximumNArgs(1),
			RunE: func(_ *cobra.Command, args []string) error {
				prefix := ""
				if len(args) == 1 {
					prefix = args[0]
				}
				text, code := runURLPathSet(a.install(), prefix)
				a.emit(text, code)
				return nil
			},
		},
		&cobra.Command{
			Use:   "reset",
			Short: "clear the panel URL prefix",
			RunE: func(_ *cobra.Command, _ []string) error {
				text, code := runURLPathReset(a.install())
				a.emit(text, code)
				return nil
			},
		},
	)
	return cmd
}

func (a *app) resetPasswordCmd() *cobra.Command {
	var adminPass string
	cmd := &cobra.Command{
		Use:   "reset-password",
		Short: "rewrite the owner credential (hashed)",
		RunE: func(_ *cobra.Command, _ []string) error {
			text, code := runResetPassword(a.install(), a.dataDir, adminPass)
			a.emit(text, code)
			return nil
		},
	}
	cmd.Flags().StringVar(&adminPass, "admin-pass", "", "new password (else $OVM_ADMIN_PASS)")
	return cmd
}

func (a *app) updateCmd() *cobra.Command {
	var opts updateOptions
	var pin string
	var deprecatedSrc string
	cmd := &cobra.Command{
		Use:   "update",
		Short: "staged update; recovers an interrupted one first",
		RunE: func(_ *cobra.Command, _ []string) error {
			if opts.build == "" {
				opts.build = deprecatedSrc
			}
			opts.pin = pin
			a.exit = runUpdate(a.install(), opts, a.out)
			return nil
		},
	}
	f := cmd.Flags()
	f.BoolVar(&opts.dryRun, "dry-run", false, "print the update plan and change nothing")
	f.StringVar(&opts.build, "build", "", "dev install from a working tree (default: cwd)")
	f.Lookup("build").NoOptDefVal = "."
	f.StringVar(&deprecatedSrc, "from-source", "", "deprecated alias of --build")
	_ = f.MarkHidden("from-source")
	f.StringVarP(&pin, "version", "v", "", "pin a release, e.g. -v v1.0.15")
	return cmd
}

func (a *app) serviceCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "service", Short: "service control (systemd/docker)"}
	for _, action := range []string{"start", "stop", "restart", "enable", "disable"} {
		act := action
		cmd.AddCommand(&cobra.Command{
			Use:   act,
			Short: act + " the panel service",
			RunE: func(_ *cobra.Command, _ []string) error {
				a.exit = runServiceAction(a.install(), act, a.out)
				return nil
			},
		})
	}
	return cmd
}

func runTLSMenu(a *app, inst Install) {
	in := os.Stdin
	if f, err := os.Open("/dev/tty"); err == nil {
		defer f.Close()
		in = f
	}
	sc := bufio.NewScanner(in)
	sc.Buffer(make([]byte, 1024), 1024*1024)
	readLine := func() string {
		if sc.Scan() {
			return sc.Text()
		}
		return ""
	}
	items := []struct{ label, action string }{
		{"Status", "status"},
		{"Issue Let's Encrypt (domain or IP)", "issue"},
		{"Self-signed certificate", "selfsigned"},
		{"Install custom cert + key", "install"},
		{"Renew (if due)", "renew"},
		{"Remove certificate", "remove"},
		{"Quit", ""},
	}
	for {
		fmt.Fprintln(a.out, "")
		fmt.Fprintln(a.out, "TLS menu:")
		for i, it := range items {
			fmt.Fprintf(a.out, "  %d) %s\n", i+1, it.label)
		}
		fmt.Fprint(a.out, "Choice: ")
		line := strings.TrimSpace(readLine())
		n := 0
		_, _ = fmt.Sscan(line, &n)
		if n < 1 || n > len(items) {
			fmt.Fprintln(a.out, "invalid choice")
			continue
		}
		if items[n-1].action == "" {
			return
		}
		switch items[n-1].action {
		case "status":
			text, code := runTLSStatus(inst)
			a.emit(text, code)
		case "issue":
			fmt.Fprint(a.out, "Domain or IP: ")
			target := strings.TrimSpace(readLine())
			if target == "" {
				continue
			}
			text, code := runTLSAcme(inst, target, "")
			a.emit(text, code)
		case "selfsigned":
			fmt.Fprint(a.out, "Domain or IP (default localhost): ")
			target := strings.TrimSpace(readLine())
			if target == "" {
				target = "localhost"
			}
			text, code := runTLSSelfSigned(inst, target)
			a.emit(text, code)
		case "install":
			fmt.Fprint(a.out, "Cert path: ")
			c := strings.TrimSpace(readLine())
			fmt.Fprint(a.out, "Key path: ")
			k := strings.TrimSpace(readLine())
			text, code := runTLSInstall(inst, strings.TrimSpace(c), strings.TrimSpace(k))
			a.emit(text, code)
		case "renew":
			text, code := runTLSRenew(inst)
			a.emit(text, code)
		case "remove":
			text, code := runTLSRemove(inst)
			a.emit(text, code)
		}
		if a.exit != 0 {
			a.exit = 0
		}
	}
}

func runInteractiveMenu(a *app, cmd *cobra.Command) {
	in := os.Stdin
	if f, err := os.Open("/dev/tty"); err == nil {
		defer f.Close()
		in = f
	}
	sc := bufio.NewScanner(in)
	sc.Buffer(make([]byte, 1024), 1024*1024)
	readLine := func() string {
		if sc.Scan() {
			return sc.Text()
		}
		return ""
	}
	items := []struct{ label, command string }{
		{"Status", "status"},
		{"Health", "health"},
		{"TLS / HTTPS", "tls"},
		{"Backup now", "backup"},
		{"Logs", "logs"},
		{"Update", "update"},
		{"Quit", ""},
	}
	for {
		fmt.Fprintln(a.out, "")
		fmt.Fprintln(a.out, "OVManager menu:")
		for i, it := range items {
			fmt.Fprintf(a.out, "  %d) %s\n", i+1, it.label)
		}
		fmt.Fprint(a.out, "Choice: ")
		line := strings.TrimSpace(readLine())
		n := 0
		_, _ = fmt.Sscan(line, &n)
		if n < 1 || n > len(items) {
			fmt.Fprintln(a.out, "invalid choice")
			continue
		}
		if items[n-1].command == "" {
			return
		}
		sub, _, err := cmd.Root().Find([]string{items[n-1].command})
		if err != nil || sub == nil {
			fmt.Fprintln(a.out, "command not found")
			continue
		}
		if err := sub.RunE(sub, []string{}); err != nil {
			fmt.Fprintln(a.out, err)
		}
	}
}
