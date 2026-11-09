# Rapport policy: what may leave this company's building (docs/SPEC.md section 6).
#
# Call:  POST /v1/data/rapport/decision  with  {"input": PolicyInput}
# Reply: {"result": {"decision": "allow"|"deny", "rule_id": "...", "reason": "..."}}
#
# Company data comes from data.org (data.json in the opa-policy ConfigMap):
#   {"org": {"org_id": "acme", "nda_with": ["bluefin"], "pricing_approved_for": []}}
#
# Rules are evaluated in order and the first match wins (an else chain). Missing data never
# allows anything: the chain ends in default_deny, and the list lookups treat absent data as empty.
package rapport

# data.org may be absent or partial (misconfigured ConfigMap): fall back to empty lists so that
# only the rules that need no company data can allow.
default org := {}

org := data.org

nda_with := object.get(org, "nda_with", [])

pricing_approved_for := object.get(org, "pricing_approved_for", [])

item := object.get(input, "item", {})

share_level := object.get(item, "share_level", "")

tags := object.get(item, "tags", [])

counterparty := object.get(input, "counterparty_org_id", "")

internal_item if share_level == "internal"

foreign_profile if {
	object.get(item, "kind", "") == "profile"
	object.get(item, "owner_persona_id", null) != object.get(input, "self_persona_id", "")
}

pricing_item if "pricing" in tags

pricing_unapproved if {
	pricing_item
	not counterparty in pricing_approved_for
}

nda_missing if not counterparty in nda_with

nda_present if counterparty in nda_with

# 1..7 in SPEC order; first match wins.
decision := {
	"decision": "deny",
	"rule_id": "internal_never_leaves",
	"reason": "Internal items never leave the company.",
} if {
	internal_item
} else := {
	"decision": "deny",
	"rule_id": "profile_owner_only",
	"reason": "A profile may only be shared by its owner.",
} if {
	foreign_profile
} else := {
	"decision": "deny",
	"rule_id": "pricing_needs_approval",
	"reason": "Pricing needs approval for this counterparty.",
} if {
	pricing_unapproved
} else := {
	"decision": "deny",
	"rule_id": "partner_needs_nda",
	"reason": "Partner-level items need an NDA with the counterparty.",
} if {
	share_level == "partner"
	nda_missing
} else := {
	"decision": "allow",
	"rule_id": "public_ok",
	"reason": "Public items may be shared.",
} if {
	share_level == "public"
} else := {
	"decision": "allow",
	"rule_id": "partner_with_nda",
	"reason": "Partner-level item shared under an NDA.",
} if {
	share_level == "partner"
	nda_present
} else := {
	"decision": "deny",
	"rule_id": "default_deny",
	"reason": "No rule allows this item.",
}
