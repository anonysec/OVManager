package users

import (
	"database/sql"
	"testing"

	_ "modernc.org/sqlite"
)

func usageTestDB(t *testing.T) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Exec(`CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT NOT NULL)`); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestAggregateNodeUsageSkipsReservedKeys(t *testing.T) {
	db := usageTestDB(t)
	if _, err := db.Exec(`INSERT INTO nodes (id, name) VALUES (1, 'alice')`); err != nil {
		t.Fatal(err)
	}
	u := userRow{Used: ptr(int64(999)), NodeUsage: `{"1": 500, "push_hash": {"1": "abc"}, "__reseed": true}`}

	total, perNode := aggregateNodeUsage(db, u)
	if total != 500 {
		t.Fatalf("total = %d, want 500", total)
	}
	if len(perNode) != 1 {
		t.Fatalf("perNode = %v, want one node entry", perNode)
	}
	entry := perNode[0]
	if entry["name"] != "alice" || entry["node_id"] != int64(1) || entry["used"] != int64(500) {
		t.Errorf("entry = %v, want alice/id 1/500", entry)
	}
}

func TestAggregateNodeUsageNameFallback(t *testing.T) {
	db := usageTestDB(t)
	if _, err := db.Exec(`INSERT INTO nodes (id, name) VALUES (2, 'newname')`); err != nil {
		t.Fatal(err)
	}
	u := userRow{NodeUsage: `{"oldname": 500, "newname": 200}`}

	total, perNode := aggregateNodeUsage(db, u)
	if total != 700 {
		t.Fatalf("total = %d, want 700", total)
	}
	if len(perNode) != 2 {
		t.Fatalf("perNode = %v, want two entries", perNode)
	}
	byName := map[string]map[string]any{}
	for _, e := range perNode {
		byName[e["name"].(string)] = e
	}
	if e := byName["oldname"]; e == nil || e["node_id"] != nil || e["used"] != int64(500) {
		t.Errorf("legacy entry = %v, want oldname/nil/500", e)
	}
	if e := byName["newname"]; e == nil || e["node_id"] != int64(2) || e["used"] != int64(200) {
		t.Errorf("name entry = %v, want newname/id 2/200", e)
	}
}

func ptr[T any](v T) *T { return &v }
