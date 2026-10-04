# Deploying Fjara to a Google Cloud VM (development server)

This puts the same Docker stack you run locally on a small Google Cloud server, behind
Caddy, which provides an HTTPS address and a shared password. Co-developers open
`https://<your-name>.duckdns.org`, enter the password, and use Fjara; your laptop can
be off.

Only the website is public. The backend (port 8000) and Qdrant (port 16333) stay bound
to `127.0.0.1` on the server, exactly as on your PC.

**Costs.** The Google Cloud Free Trial gives US$300 of credit for 90 days to new
customers and does not charge automatically. An `e2-medium` server in Singapore with a
30 GB disk and a static IP costs roughly US$35–40 a month, about US$110 for the trial
(estimate; check Google's pricing calculator).
Gemini API usage is billed to your Gemini key as now; trial credit cannot pay for it.
Every question costs Gemini credits, which is why the password matters.

**When the trial ends** (90 days or credit used up): upgrade to a paid account to keep
the server running unchanged, or it is stopped and, after a 30-day grace period,
permanently deleted. Keep the knowledge-base snapshot from step 1.

---

## 1. Export the knowledge base on your PC

With Docker running and the stack up locally, from the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\export-knowledge-base.ps1
```

It saves `deploy\snapshots\fjara_knowledge_v1-....snapshot` (git-ignored) and prints the
chunk count (1,648). The snapshot holds the stored embeddings, so the server needs no
re-indexing and no Gemini credits for it.

## 2. Start the Google Cloud trial and create a project

1. Open <https://cloud.google.com/free> and choose **Get started for free**. Sign in with
   Google, choose your country, and add a card (identity check only).
2. In the console (<https://console.cloud.google.com>), create a project, e.g. `fjara-dev`.
3. Open **Compute Engine → VM instances** and click **Enable** for the Compute Engine API
   if asked.

## 3. Create the server

**Compute Engine → VM instances → Create instance**:

| Setting | Value |
|---|---|
| Name | `fjara-dev` |
| Region / zone | `asia-southeast1` (Singapore), any zone |
| Machine type | `e2-medium` (2 vCPU, 4 GB) |
| Boot disk | **Change** → Ubuntu, **Ubuntu 24.04 LTS (x86/64)**, Balanced disk, **30 GB** |
| Firewall | Tick **Allow HTTP traffic** and **Allow HTTPS traffic** |

Click **Create**. Smaller machines (`e2-small`, `e2-micro`) do not have enough memory to
build the frontend image.

**Make the IP address permanent.** Open **VPC network → IP addresses**, find the
server's external address and choose **Promote to static IP address** (name it
`fjara-dev-ip`). Otherwise the address can change when the server restarts.

## 4. Give the server a name (DuckDNS, free)

1. Go to <https://www.duckdns.org> and sign in.
2. Add a subdomain, e.g. `fjara-dev` → `fjara-dev.duckdns.org`.
3. Paste the server's static IP into **current ip** and click **update ip**.

Caddy needs this name to get an HTTPS certificate; bare IP addresses are not used.

## 5. Install Docker on the server

On the **VM instances** page, click **SSH** next to `fjara-dev`. A terminal opens in the
browser. Run:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Click **SSH** again (so the group change applies) and check:

```bash
docker run --rm hello-world
```

## 6. Get the code

```bash
git clone https://github.com/mark-anthony-canta/fjara.git
cd fjara
git checkout codex/gcp-deploy
```

If the repository is private, Git asks for a username and password. Use your GitHub
username and, as the password, a **fine-grained personal access token**: GitHub →
Settings → Developer settings → Personal access tokens → Fine-grained tokens →
Generate new token, repository access **Only select repositories → fjara**, permission
**Contents: Read-only**.

## 7. Add the secrets (never committed)

```bash
nano .env
```

Paste the same lines as the `.env` on your PC (Firecrawl key, Gemini key, models,
`QDRANT_URL=http://localhost:16333`, `QDRANT_COLLECTION=fjara_knowledge_v1`). Save with
**Ctrl+O, Enter**, exit with **Ctrl+X**.

Create the password hash (replace `choose-a-password`):

```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'choose-a-password'
```

Then:

```bash
cp deploy/caddy.env.example deploy/caddy.env
nano deploy/caddy.env
```

Set `SITE_ADDRESS` to your DuckDNS name, choose `BASIC_AUTH_USER`, and paste the hash into
`BASIC_AUTH_HASH`, **keeping the single quotes** around it.

## 8. Restore the knowledge base

In the SSH window, click the **gear/upload** button (**Upload file**) and upload the
snapshot from `deploy\snapshots\` on your PC. It lands in your home directory. Then:

```bash
docker compose up -d qdrant
bash deploy/restore-knowledge-base.sh ~/fjara_knowledge_v1-*.snapshot
```

It should end with `"points_count":1648`.

## 9. Start Fjara

```bash
docker compose -f compose.yaml -f deploy/compose.prod.yaml up -d --build
```

The first build takes several minutes. Then check:

```bash
docker compose -f compose.yaml -f deploy/compose.prod.yaml ps
curl -s http://127.0.0.1:8000/ready
```

Open `https://fjara-dev.duckdns.org` in a browser, enter the username and password, and
ask a question. The certificate is issued on the first visit, which can take a few
seconds.

Share the address, username and password with your co-developers. To revoke access,
generate a new hash, update `deploy/caddy.env`, and run the command from step 9 again.

## 10. Protect the budget

In **Billing → Budgets & alerts**, create a budget (e.g. US$40/month) with email alerts.
Do this before upgrading from the trial.

---

## Everyday operations

All commands run in the `fjara` folder on the server.

| Task | Command |
|---|---|
| Deploy new code | `git pull && docker compose -f compose.yaml -f deploy/compose.prod.yaml up -d --build` |
| View logs | `docker compose -f compose.yaml -f deploy/compose.prod.yaml logs -f --tail 100` |
| Restart | `docker compose -f compose.yaml -f deploy/compose.prod.yaml restart` |
| Stop Fjara | `docker compose -f compose.yaml -f deploy/compose.prod.yaml down` (never add `-v`: it deletes the knowledge base) |

Services restart automatically when the server reboots. To save credit when nobody is
testing, **Stop** the VM on the VM instances page and **Start** it again later; the
static IP keeps the address the same. A stopped VM still bills for its disk and static
IP (an unattached or idle static IP is billed at a higher rate), roughly US$10 a month.

## Troubleshooting

- **Browser shows a certificate or connection error:** check that DuckDNS points at the
  static IP, that HTTP and HTTPS were allowed when the VM was created, and run
  `docker compose -f compose.yaml -f deploy/compose.prod.yaml logs caddy`.
- **Password is always rejected:** the hash must be wrapped in single quotes in
  `deploy/caddy.env`; recreate Caddy after editing it with the step 9 command.
- **Answers say a provider limit was reached (429):** the Gemini key is out of quota or
  credit, not a server problem.
- **`/ready` reports 0 chunks:** repeat step 8.
