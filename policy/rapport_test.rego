# Tests for deploy/policy/rapport.rego: every SPEC section 6 test vector plus edge cases.
# Run:  opa test deploy/policy policy -v
#
# Company data is supplied with `with data.org as ...` so the tests do not depend on how OPA
# namespaces the data files under deploy/policy/data/.
package rapport_test

import data.rapport

acme := {"org_id": "acme", "nda_with": ["bluefin"], "pricing_approved_for": []}

bluefin := {"org_id": "bluefin", "nda_with": ["acme"], "pricing_approved_for": []}

# org=acme, self=acme.ava, counterparty=bluefin unless the test overrides a field.
acme_input(item) := {
	"action": "offer",
	"org_id": "acme",
	"self_persona_id": "acme.ava",
	"counterparty_org_id": "bluefin",
	"encounter_id": "enc-test0001",
	"item": item,
}

item_of(kind, level, tags) := {
	"item_id": "item-1",
	"kind": kind,
	"share_level": level,
	"tags": tags,
}

# ---------------------------------------------------------------- SPEC section 6 vectors
test_pricing_partner_denied if {
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["pricing"])) with data.org as acme
	d.decision == "deny"
	d.rule_id == "pricing_needs_approval"
}

test_security_partner_allowed_with_nda if {
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["security"])) with data.org as acme
	d.decision == "allow"
	d.rule_id == "partner_with_nda"
}

test_public_allowed if {
	d := rapport.decision with input as acme_input(item_of("document", "public", ["healthcare"])) with data.org as acme
	d.decision == "allow"
	d.rule_id == "public_ok"
}

test_internal_never_leaves if {
	d := rapport.decision with input as acme_input(item_of("document", "internal", ["anything"])) with data.org as acme
	d.decision == "deny"
	d.rule_id == "internal_never_leaves"
}

test_internal_beats_everything_else if {
	# Internal plus pricing plus a foreign profile: rule 1 still wins.
	item := object.union(item_of("profile", "internal", ["pricing"]), {"owner_persona_id": "acme.sam"})
	d := rapport.decision with input as acme_input(item) with data.org as acme
	d.rule_id == "internal_never_leaves"
}

test_profile_of_someone_else_denied if {
	item := object.union(item_of("profile", "public", []), {"owner_persona_id": "acme.sam"})
	d := rapport.decision with input as acme_input(item) with data.org as acme
	d.decision == "deny"
	d.rule_id == "profile_owner_only"
}

test_own_profile_allowed if {
	item := object.union(item_of("profile", "public", []), {"owner_persona_id": "acme.ava"})
	d := rapport.decision with input as acme_input(item) with data.org as acme
	d.decision == "allow"
	d.rule_id == "public_ok"
}

test_partner_without_nda_denied if {
	inp := object.union(acme_input(item_of("document", "partner", ["security"])), {"counterparty_org_id": "globex"})
	d := rapport.decision with input as inp with data.org as acme
	d.decision == "deny"
	d.rule_id == "partner_needs_nda"
}

# ---------------------------------------------------------------- Bluefin answers Acme
test_bluefin_answers_acme_partner_with_nda if {
	inp := {
		"action": "answer",
		"org_id": "bluefin",
		"self_persona_id": "bluefin.bo",
		"counterparty_org_id": "acme",
		"encounter_id": "enc-test0001",
		"item": item_of("document", "partner", ["requirements"]),
	}
	d := rapport.decision with input as inp with data.org as bluefin
	d.decision == "allow"
	d.rule_id == "partner_with_nda"
}

test_bluefin_pricing_denied_for_acme if {
	inp := {
		"action": "answer",
		"org_id": "bluefin",
		"self_persona_id": "bluefin.bo",
		"counterparty_org_id": "acme",
		"encounter_id": "enc-test0001",
		"item": item_of("document", "partner", ["pricing"]),
	}
	d := rapport.decision with input as inp with data.org as bluefin
	d.rule_id == "pricing_needs_approval"
}

# ---------------------------------------------------------------- pricing approval and ordering
test_pricing_allowed_when_counterparty_is_approved if {
	approved := object.union(acme, {"pricing_approved_for": ["bluefin"]})
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["pricing"])) with data.org as approved
	d.decision == "allow"
	d.rule_id == "partner_with_nda"
}

test_pricing_rule_beats_public_ok if {
	d := rapport.decision with input as acme_input(item_of("document", "public", ["pricing"])) with data.org as acme
	d.rule_id == "pricing_needs_approval"
}

test_unknown_share_level_default_denied if {
	d := rapport.decision with input as acme_input(item_of("document", "secret", [])) with data.org as acme
	d.decision == "deny"
	d.rule_id == "default_deny"
}

# ---------------------------------------------------------------- missing data still denies
test_missing_company_data_denies_partner if {
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["security"])) with data.org as {}
	d.decision == "deny"
	d.rule_id == "partner_needs_nda"
}

test_missing_company_data_denies_pricing if {
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["pricing"])) with data.org as {}
	d.decision == "deny"
	d.rule_id == "pricing_needs_approval"
}

test_empty_input_default_denied if {
	d := rapport.decision with input as {} with data.org as acme
	d.decision == "deny"
	d.rule_id == "default_deny"
}

test_missing_item_fields_default_denied if {
	d := rapport.decision with input as acme_input({"item_id": "item-1"}) with data.org as acme
	d.decision == "deny"
	d.rule_id == "default_deny"
}

test_profile_without_owner_denied if {
	d := rapport.decision with input as acme_input(item_of("profile", "public", [])) with data.org as acme
	d.decision == "deny"
	d.rule_id == "profile_owner_only"
}

# ---------------------------------------------------------------- shipped data files
# deploy/policy/data/<org>/data.json is loaded by `opa test` under data.data.<org> (one directory
# per org so the two files never merge). Check the files themselves match the fixtures above.
test_shipped_acme_data if {
	data.data.acme.org == acme
}

test_shipped_bluefin_data if {
	data.data.bluefin.org == bluefin
}

test_shipped_acme_data_denies_pricing_for_bluefin if {
	d := rapport.decision with input as acme_input(item_of("document", "partner", ["pricing"])) with data.org as data.data.acme.org
	d.decision == "deny"
	d.rule_id == "pricing_needs_approval"
}
