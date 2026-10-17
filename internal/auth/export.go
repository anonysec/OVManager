// Password policy reuse for the CLI (cli/password.py validate), so the browser
// claim and `ovm reset-password` cannot drift.
package auth

// PasswordProblem returns a human reason when password violates panel policy,
// else "". Mirrors cli/password.validate -> backend.validation.password_problem.
func PasswordProblem(password string) string { return passwordProblem(password) }
