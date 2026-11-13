"""Render the public evidence trail, optionally joined to private data on read."""

import json
from datetime import datetime

from .relevance import portfolio_context
from .store import WINDOW, timeline


def report(db, cutoff, *, history=False, portfolio=None, after_sequence=0, received_at=None):
    rows = timeline(db, cutoff, history=history, after_sequence=after_sequence)
    if received_at is not None:
        rows = [row for row in rows if row["seen_at"] == received_at]
    if not rows:
        print("No watch entries at this cutoff.")
        return
    references = {}

    def cite(url):
        if url not in references:
            references[url] = len(references) + 1
        return f"[{references[url]}]"

    for row in rows:
        facts = json.loads(row["facts"])
        links = json.loads(row["links"])
        names = sorted({link["ticker"] for link in links})
        context_at = row["seen_at"] if history else cutoff
        candidate = row["kind"] == "issuer_candidate"
        heading = f"ISSUER FOLLOW-UP FOR REVIEW | {row['status'].upper()}" if candidate else row["status"].upper()
        print(f"\n{heading}  {' / '.join(names)}  |  {row['incident']}")
        print(f"  Received {row['seen_at']}   Source version {row['revision']}")
        print(f"  {row['source']}: {row['title']} {cite(row['url'])}")
        issuer = candidate or row["kind"] == "operator_update"
        if issuer:
            if candidate:
                print(f"  Issuer excerpt: {facts['excerpt']} {cite(row['url'])}")
                print(f"  Stated earthquake date in Taiwan: {facts['event_date']}. "
                      f"Document first seen {facts['first_seen']}.")
            else:
                print(f"  Evidence: {facts['locator']} {facts['clock_basis']}")
            print(f"  Uncertainty: {facts['uncertainty']}")
            print(f"  Next: {facts['next_check']}")
        else:
            print(f"  Magnitude {facts['magnitude']}. Origin {row['occurred_at']} "
                  f"at {facts['latitude']}, {facts['longitude']}.")
            if row["status"] == "withdrawn":
                print("  The revised hazard no longer qualifies for this watch. See the original match in history.")
            else:
                for site in {link["site"]: link for link in links}.values():
                    print(f"  {site['supplier']} / {site['site']}: about {site['distance_km']} km "
                          f"to the screening point. {site['coordinate_basis']} {cite(site['coordinates_url'])}")
                    if "radius_km" in site:
                        print(f"  Rule: M{site['min_magnitude']:g}+ within {site['radius_km']:g} km "
                              f"of {site['screen_latitude']}, {site['screen_longitude']}.")
                print("  Uncertainty: fab interruption and customer shipment effects are unconfirmed.")
                print("  Next: check TSMC's operations statement within 24 hours of the quake "
                      "for evacuations, tool downtime or evidence of recovery.")

        if row["status"] != "withdrawn" and (not issuer or candidate or not history):
            if issuer:
                trigger = db.execute("SELECT o.url FROM observations o JOIN inbox i USING(id,revision) "
                                     "WHERE i.incident=? ORDER BY i.sequence LIMIT 1", (row["incident"],)).fetchone()
                print(f"  Original earthquake screen {cite(trigger['url'])}")
            for link in links:
                print(f"  {link['ticker']}: {link['scope']} {link['limit']} "
                      f"{link['locator']} ({link['filed_on']}) {cite(link['source_url'])}")
            for site in {link["site"]: link for link in links}.values():
                print(f"  Supplier site: {site['site_locator']} {cite(site['site_url'])}")

        # The operator can confirm a disruption independently of the geographic
        # screen. Surface later hazard evidence without undoing that statement.
        hazard = db.execute("SELECT * FROM observations WHERE id=? AND seen_at<=? "
                            "ORDER BY revision DESC LIMIT 1", (row["incident"], context_at)).fetchone()
        if hazard and hazard["seen_at"] > row["seen_at"]:
            label = "USGS withdrawal" if hazard["kind"] == "withdrawn" else "Updated USGS observation"
            print(f"  {label}, {hazard['revision']}: {hazard['title']} {cite(hazard['url'])}")
        if row["status"] not in {"closed", "withdrawn"}:
            review_from = row["occurred_at"] if row["kind"] == "earthquake" else row["seen_at"]
            if datetime.fromisoformat(context_at) - datetime.fromisoformat(review_from) > WINDOW:
                print("  Review overdue. Check the operator for a newer statement.")
            if portfolio:
                try:
                    context = portfolio_context(portfolio, names, context_at)
                except (OSError, ValueError):
                    context = "Watchlist only. Could not read or reconcile the supplied portfolio."
                print(f"  Private view: {context}")
    print("\nSources")
    for url, index in references.items():
        print(f"  [{index}] {url}")
