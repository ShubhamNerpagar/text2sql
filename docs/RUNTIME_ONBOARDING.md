# Runtime semantic onboarding

Version 7.0 ships without country/customer semantic packages. Connect a real source and use `POST /api/onboarding/bootstrap` or **Admin → Onboarding**. The platform discovers metadata only, writes the physical ontology, generates inferred semantic drafts, creates relationship candidates, and builds GraphRAG. See the root `README.md` for source-specific configuration and S3 placement.
