# Bruno environments

- `dev.bru` — committed, **placeholders only**. No real tokens, codes, or
  account-specific ids. (Bruno persists edited values back to the selected env
  file, so do not enter real values into this one.)
- `dev.local.bru.example` — a copy-me template.
- `dev.local.bru` — **git-ignored** (`bruno/**/environments/*.local.bru`); put
  your real values here.

## Set up a local environment with real values

```bash
cd bruno/imagenetog-redux/environments
cp dev.local.bru.example dev.local.bru
```

Bruno loads every `.bru` file in this folder as a selectable environment, so
`dev.local` will appear in the environment picker — select it and fill in real
values there.

Fill in from `terraform -chdir=terraform/environments/dev output`:

- `baseUrl` — `terraform output -raw api_invoke_url` (already `…/dev/v1`)
- `hostedUiDomain` — `<hosted_ui_domain>.auth.us-east-1.amazoncognito.com`
- `appClientId` — `terraform output -raw app_client_id`
- `testCollection` / `testImageKey` — an existing collection + image key

## Get an ID token for `authToken`

Send the token as the **raw** `Authorization` header value — **no `Bearer`
prefix**. Fastest path (AWS CLI, `USER_PASSWORD_AUTH` is enabled on the client):

```bash
CLIENT_ID="$(terraform -chdir=terraform/environments/dev output -raw app_client_id)"
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME=tester@example.com,PASSWORD='<password>' \
  --query 'AuthenticationResult.IdToken' --output text
```

Paste the value into `authToken` in `dev.local.bru`. ID tokens expire after
~1 hour — re-mint and update as needed. (Alternatively use the browser hosted-UI
flow: paste the redirect `code` into `authCode` and run **Auth → Get Token**,
which sets `authToken` automatically.)

See the repository README section "API spec & Bruno collection" for the full
walkthrough.
