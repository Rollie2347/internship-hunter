"""Phase 6: a Streamlit dashboard over data/tracker.db -- companies,
postings, contacts, and messages with status, plus 7-day follow-up
reminders (see dashboard/followups.py for the actual date logic, which is
tested separately without needing Streamlit running at all).

Run with (from the internship-hunter folder, PowerShell):
    streamlit run internship_hunter/dashboard/app.py
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from internship_hunter import config, db
from internship_hunter.approvals import queue
from internship_hunter.dashboard import followups
from internship_hunter.drafting import compose, daily_cap, gmail_client
from internship_hunter.linkedin_assist import assist as linkedin
from internship_hunter.models import Message

st.set_page_config(page_title="Internship Hunter", layout="wide")

conn = db.get_connection()
db.init_db(conn)

companies = db.list_companies(conn)
postings = db.list_postings(conn)
contacts = db.list_contacts(conn)
messages = db.list_messages(conn)
companies_by_id = {c.id: c.name for c in companies}
due_for_follow_up = followups.filter_needing_follow_up(messages)

st.title("Internship Hunter")

# The referral pipeline: each person counted once, at the furthest stage reached.
steps = queue.funnel(messages)
f1, f2, f3, f4 = st.columns(4)
f1.metric("People contacted", steps["contacted"])
f2.metric("Replied", steps["replied"])
f3.metric("Calls", steps["calls"])
f4.metric("Referrals", steps["referrals"])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Companies", len(companies))
c2.metric("Postings", len(postings))
c3.metric("Contacts", len(contacts))
c4.metric("Messages", len(messages))
c5.metric("Follow-ups due", len(due_for_follow_up))

tab_applications, tab_companies, tab_postings, tab_contacts, tab_messages, tab_linkedin = st.tabs(
    ["Applications", "Companies", "Postings", "Contacts", "Emails & Follow-ups", "LinkedIn & notes"]
)

with tab_applications:
    # Read-only view of the Telegram approval queue (see approvals/bot.py,
    # which is where applications actually get approved and opened).
    applications = db.list_applications(conn)
    postings_by_id = {p.id: p for p in postings}
    st.text(queue.build_status_text(conn))
    st.dataframe(
        [
            {
                "#": a.id,
                "Status": a.status,
                "Company": companies_by_id.get(postings_by_id[a.posting_id].company_id, "?"),
                "Title": postings_by_id[a.posting_id].title,
                "Location": postings_by_id[a.posting_id].location,
                "Proposed": a.proposed_at,
                "Submitted": a.submitted_at or "",
                "Days waiting": queue.days_since_submitted(a),
                "URL": postings_by_id[a.posting_id].url,
            }
            for a in applications if a.posting_id in postings_by_id
        ],
        column_config={"URL": st.column_config.LinkColumn()},
        use_container_width=True,
        hide_index=True,
    )

with tab_companies:
    tiers = sorted({c.priority_tier for c in companies})
    states = sorted({c.state for c in companies if c.state})
    col_a, col_b = st.columns(2)
    tier_filter = col_a.multiselect("Tier", tiers, format_func=lambda t: f"{t} - {config.PRIORITY_TIERS[t]}")
    state_filter = col_b.multiselect("State", states)
    rows = [
        c for c in companies
        if (not tier_filter or c.priority_tier in tier_filter)
        and (not state_filter or c.state in state_filter)
    ]
    st.dataframe(
        [
            {
                "Tier": c.priority_tier,
                "Name": c.name,
                "State": c.state,
                "City": c.city,
                "What they build": c.what_they_build,
                "Needs verification": c.needs_verification,
                "No ATS feed found": c.manual_check_needed,
                "Careers URL": c.careers_url,
            }
            for c in rows
        ],
        column_config={"Careers URL": st.column_config.LinkColumn()},
        use_container_width=True,
        hide_index=True,
    )

with tab_postings:
    skill_options = sorted({p.skill_match for p in postings})
    skill_filter = st.multiselect("Skill fit", skill_options)
    rows = [p for p in postings if not skill_filter or p.skill_match in skill_filter]
    st.dataframe(
        [
            {
                "Company": companies_by_id.get(p.company_id, "?"),
                "Title": p.title,
                "Location": p.location,
                "Skill fit": p.skill_match,
                "Software?": p.is_software_role,
                "Intern/jr?": p.is_intern_or_junior,
                "Clearance?": p.clearance_required,
                "Citizenship?": p.citizenship_required,
                "First seen": p.first_seen_date,
                "URL": p.url,
            }
            for p in rows
        ],
        column_config={"URL": st.column_config.LinkColumn()},
        use_container_width=True,
        hide_index=True,
    )

with tab_contacts:
    st.dataframe(
        [
            {
                "Company": companies_by_id.get(c.company_id, "?"),
                "Name": c.name,
                "Title": c.title,
                "Fact": c.fact,
                "Email": c.email or "",
                "Found via": c.source_kind,
                "Source": c.source_url,
            }
            for c in contacts
        ],
        column_config={"Source": st.column_config.LinkColumn()},
        use_container_width=True,
        hide_index=True,
    )

with tab_messages:
    st.caption(f"{daily_cap.remaining_today(conn)} Gmail draft(s) left today (cap: {config.DAILY_DRAFT_CAP}/day).")

    if due_for_follow_up:
        st.subheader(f"⚠️ {len(due_for_follow_up)} message(s) need a follow-up")
        for m in due_for_follow_up:
            days = followups.days_since_sent(m)
            header = f"{companies_by_id.get(m.company_id, '?')} — {m.subject} (sent {days} days ago, no reply)"
            with st.expander(header):
                st.text(m.body)
                if st.button("Draft follow-up", key=f"followup_{m.id}"):
                    if not config.ANTHROPIC_API_KEY:
                        st.error("ANTHROPIC_API_KEY is not set in .env.")
                    else:
                        try:
                            daily_cap.enforce_daily_cap(conn)
                        except daily_cap.DailyCapReached as exc:
                            st.error(str(exc))
                        else:
                            import anthropic

                            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
                            company = next(c for c in companies if c.id == m.company_id)
                            contact = next((c for c in contacts if c.id == m.contact_id), None) if m.contact_id else None
                            posting = next((p for p in postings if p.id == m.posting_id), None) if m.posting_id else None
                            profile_text = config.ABOUT_ME_PATH.read_text(encoding="utf-8") if config.ABOUT_ME_PATH.exists() else ""
                            resume_text = config.RESUME_PATH_TXT.read_text(encoding="utf-8") if config.RESUME_PATH_TXT.exists() else ""
                            follow_up_context = followups.build_follow_up_context(m)

                            draft = compose.compose_email(
                                client, profile_text, resume_text, company,
                                contact=contact, posting=posting, follow_up_context=follow_up_context,
                            )
                            try:
                                service = gmail_client.get_service()
                                draft_id = gmail_client.create_draft(
                                    service, draft.subject, draft.body,
                                    to_email=(contact.email if contact else None),
                                )
                            except RuntimeError as exc:
                                st.error(str(exc))
                            else:
                                db.insert_message(conn, Message(
                                    company_id=m.company_id, contact_id=m.contact_id, posting_id=m.posting_id,
                                    channel="email", subject=draft.subject, body=draft.body,
                                    gmail_draft_id=draft_id, status="drafted",
                                ))
                                st.success(f"Follow-up drafted and saved to Gmail (id {draft_id}). Review it there.")
                                st.text(draft.body)

    st.subheader("All messages")
    st.dataframe(
        [
            {
                "Created": m.created_at,
                "Company": companies_by_id.get(m.company_id, "?"),
                "Channel": m.channel,
                "Subject": m.subject,
                "Status": m.status,
                "Sent": m.sent_at or "",
                "Days since sent": followups.days_since_sent(m),
                "Gmail draft id": m.gmail_draft_id or "",
            }
            for m in messages
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Update a message's status")
    if messages:
        labels = [f"#{m.id} — {companies_by_id.get(m.company_id, '?')} — {m.subject}" for m in messages]
        selected = st.selectbox("Message", labels)
        selected_message = messages[labels.index(selected)]
        new_status = st.selectbox(
            "New status", config.MESSAGE_STATUSES,
            index=config.MESSAGE_STATUSES.index(selected_message.status),
        )
        if st.button("Update status"):
            sent_at = (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if (new_status == "sent" and selected_message.status != "sent")
                else None
            )
            db.update_message_status(conn, selected_message.id, new_status, sent_at=sent_at)
            st.success(f"Marked #{selected_message.id} as {new_status}.")
            st.rerun()
    else:
        st.caption("No messages yet.")

with tab_linkedin:
    # Read-only: cards are sent, and marked sent/replied, from Telegram (see
    # linkedin_assist/assist.py). Nothing here or there opens LinkedIn.
    cards = [m for m in messages if m.channel in linkedin.MANUAL_CHANNELS]
    contacts_by_id = {c.id: c for c in contacts}
    l1, l2, l3, l4, l5 = st.columns(5)
    l1.metric("Cards today", f"{linkedin.cards_today(conn)} / {config.LINKEDIN_DAILY_CAP}")
    l2.metric("Waiting on you", sum(1 for m in cards if m.status == "drafted"))
    l3.metric("Sent, no answer yet", sum(1 for m in cards if m.status == "sent"))
    l4.metric("Replied", sum(1 for m in cards if m.status == "replied"))
    l5.metric("Skipped / not found", sum(1 for m in cards if m.status in ("skipped", "not_found")))
    st.dataframe(
        [
            {
                "#": m.id,
                "Status": m.status.replace("_", " "),
                "Via": "LinkedIn" if m.channel == linkedin.CHANNEL else "pasted note",
                "Person": contacts_by_id[m.contact_id].name if m.contact_id in contacts_by_id else "?",
                "Title": contacts_by_id[m.contact_id].title if m.contact_id in contacts_by_id else "",
                "Company": companies_by_id.get(m.company_id, "?"),
                "Card made": m.created_at,
                "Sent": m.sent_at or "",
                "Days since sent": followups.days_since_sent(m),
                "Reminded": m.reminded_at or "",
                "Note": m.body,
            }
            for m in cards
        ],
        use_container_width=True,
        hide_index=True,
    )
    replies = [m for m in messages if m.channel.endswith("_reply")]
    if replies:
        st.subheader("Follow-up messages drafted after a reply")
        for m in replies:
            with st.expander(f"{companies_by_id.get(m.company_id, '?')} — {m.subject}"):
                st.text(m.body)
