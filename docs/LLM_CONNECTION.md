# Connect Ask to Amazon Bedrock

The application uses boto3's Bedrock **Converse** API. Choose an available conversational model or inference profile in your account and region; a stronger model is an option, not a replacement for certified business definitions.

1. Provide AWS authentication to the application process: an EC2 instance role in deployment, or an AWS CLI/SSO profile for local development. For SSO, run `aws sso login --profile YOUR_PROFILE` outside the application and make that profile available to its service identity.
2. Set `AWS_REGION` and `BEDROCK_REGION` in secure instance configuration or `.env`. Set `AWS_PROFILE` only when that named profile actually exists for the user running Python. An unavailable profile prevents boto3 authentication even if another identity could otherwise be used.
3. Grant `bedrock:ListFoundationModels`, `bedrock:ListInferenceProfiles` and `bedrock:InvokeModel` for the models/profiles you intend to use. Cross-region inference profiles may require invocation permission for their destination models. Use the existing `infra/windows/ec2-instance-role-policy.json` as a template and scope it to your account.
4. Permit outbound HTTPS to the Bedrock control and runtime endpoints for the chosen region and any destinations required by the inference profile. Warehouse/catalog endpoints need their own network access.
5. Open **Administration → AI Models**, discover the catalog, click **Test access** on the intended model, and obtain **Verified**. This performs a small paid Converse request; listing a model is not proof of invocation access.
6. Select verified models for **Semantic planning** and **Semantic verification**, then save configuration. They can be the same model. `/api/llm/status` reports readiness with `offline_fallback: false`.
7. Prepare and activate certified data definitions before asking a question. Every accepted new question uses a planning call and a separate semantic review call. Clarifications may finish after the first call.

A failure returns a connection, availability or response error and does not execute a query. The application never falls back to a local natural-language planner. Saved reports recompile previously reviewed plans; they do not reinterpret their questions on every scheduled refresh.

In the development environment used for this change, the configured AWS profile was unavailable and no usable alternative credential chain was found. No live LLM or live warehouse answer was claimed. Configure credentials through your AWS/environment settings; do not paste credentials into chat or package them with the application.

`APP_MODE=local` controls local platform state, not offline answering. Metadata browsing and deterministic graph inspection remain available for setup. `ENABLE_SAMPLE_EXECUTION=true` makes the optional Contoso source selectable, including in a secured production installation. It does not enable offline answering. Set it to false if the installation should not offer sample execution.
