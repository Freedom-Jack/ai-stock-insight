# IBKR watchlist research findings

**Reviewed:** 20 November 2026. **Method:** official public documentation only. No account login, brokerage API call, credentials, or private account data were used. These are documented capabilities and limitations, not verification against the user's account. The resulting specification is [Watchlist synchronization design](../design/WATCHLIST_SYNC.md).

## 1. Findings by integration route

The user has now identified **IBKR Client Portal and Mobile** as the actual watchlist interfaces. IBKR's [Client Portal synchronization FAQ](https://www.interactivebrokers.com/support/faq/content/sync-watchlist-client-portal-109016343) says synchronized Mobile/TWS watchlists are available under Research → Watchlist → My Lists. Stock Insight can consume a selected IBKR list; it does not need to reconcile the user's IBKR applications with one another.

| Route | Verified capability | Limitation relevant to this project |
|---|---|---|
| Client Portal/Mobile list | Existing IBKR lists can be viewed and managed through these interfaces. | Inspected official guides did not establish a selected-saved-list export or clipboard command. Manual instrument input is a proposed Stock Insight fallback, not a verified native export. |
| TWS financial-instruments export | An existing watchlist can export its contracts to a file. | A manually produced snapshot; automatic refresh of that local file is not established. |
| Web API watchlist endpoints | Enumerate saved lists and retrieve a chosen list's instruments. | Normal documented `/iserver` access uses a broader brokerage session; a watchlist-only broker permission is unproven. |
| TWS socket API | Provides quote data for specified contracts. | “Watchlist data” terminology does not establish saved-list enumeration; connecting automatically delivers managed account IDs. |

IBKR says user watchlists saved in Client Portal, Mobile, and TWS synchronize across its platforms. The Portfolio tab separately displays holdings, balances, and margin information. This supports treating a selected watchlist as a distinct source, but does not imply an exported file stays synchronized. Source: [Monitor Panel guide](https://www.ibkrguides.com/traderworkstation/monitor-panel.htm).

## 2. Current-user onboarding and optional export

The [Client Portal watchlist guide](https://www.ibkrguides.com/clientportal/researchmenu/watchlist.htm), [iPhone guide](https://www.ibkrguides.com/iphone/watchlist.htm) and [Android lesson](https://www.interactivebrokers.com/campus/trading-lessons/creating-watchlists-and-scanners-android/) describe viewing, creating, editing and synchronizing lists. No selected-watchlist file/clipboard export was established from those pages. This does not prove that every current app version lacks such a feature. Client Portal's documented [Export to CSV for Market Screener](https://www.ibkrguides.com/clientportal/researchmenu/market-screener.htm) concerns screener results; it is not evidence of export for an existing saved watchlist.

For the initial trial, the proposed fallback is to paste/transcribe only instrument symbols and identifying fields into Stock Insight, or supply an instrument-only CSV. Keep the list externally authoritative and the observation labeled manual. Avoid complete screen/table copies that could include configured position/P&L columns. TWS installation is unnecessary for this path.

### Optional TWS financial-instruments route

The official FAQ describes **File → Import/Export → Export Financial Instruments** from an existing watchlist and recommends a small test export to inspect the actual format. Source: [TWS instrument import/export FAQ](https://www.interactivebrokers.com/support/faq/content/34485530).

The related import guide supports comma-delimited `.txt` and `.csv`, one instrument per line, using:

```text
DES, UNDERLYING, SECTYPE, EXCHANGE, LASTTRADINGDAY, STRIKE, PUT/CALL, MULTIPLIER
SYM, SYMBOL, EXCHANGE
CON, CONID, EXCHANGE
```

For equities, `DES` uses security type `STK` and placeholders for derivative fields; `SYM` carries symbol/exchange; `CON` carries contract ID/exchange. Entries are uppercase. This is the documented **import** contract, not a guarantee of identical export bytes across TWS versions. Source: [Import Tickers from a File](https://www.ibkrguides.com/traderworkstation/import-tickers-from-a-file.htm), updated October 29, 2026.

An exported contract list and an exported screen/table are different artifacts. The latter can include whichever additional columns are configured. No documentation inspected established a continually refreshed financial-instruments export or a stable automatically synchronized local path.

## 3. Web API endpoints and payloads

### Enumeration: unresolved reference inconsistency

[Get All Watchlists](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists) identifies `GET /iserver/watchlists`. Its sample instead requests singular `/iserver/watchlist?SC=USER_WATCHLIST`. The page also labels `SC` a body parameter while placing it in the sample query. This inconsistency remains unresolved; no live request was made to choose between them.

The response describes user/system lists with IDs, names, type, editability, and internal flags. Its example includes `modified`, whose ordering/version semantics are not defined sufficiently for a synchronization guarantee. `SC` filters the request; it is not an OAuth permission. The response's `read_only` flag describes whether that list is editable.

### Selected list membership

[Get Watchlist Information](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-watchlist-information) documents `GET /iserver/watchlist?id=<list-id>`. The payload contains `id`, `hash`, `name`, `readOnly`, and `instruments`. Instrument fields include `C`, `conid`, `name`, `fullName`, `assetClass`, `ticker`, and `chineseName`; the example includes `ST`.

IBKR explicitly notes that a first request may return only contract IDs and names; later requests can add metadata. The documented schema contains no positions, quantities, balances, or P&L. This describes the endpoint response, not the authority of the session. The page does not establish a strong change-token contract for `hash`.

## 4. Authorization and session constraints

The [session FAQ](https://www.interactivebrokers.com/support/faq/content/long-web-api-session-last-629305657) distinguishes an outer read-only session from a brokerage session. The outer layer can access portfolio data but does not permit `/iserver`; the brokerage layer enables that endpoint family and confers broader access. Therefore “read-only session” and “watchlist-only permission” are materially different claims.

[Trading session guidance](https://www.interactivebrokers.com/docs/web-api/authentication/trading) states that brokerage sessions expire after more than five idle minutes and can be kept alive. Its generic startup sequence recommends `/iserver/accounts` after initialization and shows `compete=true`. [Multiple-session documentation](https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions) allows one active brokerage session per username across platforms. A watchlist-specific exception or a supported account-data-free startup path has not been demonstrated here.

The [gateway limitations](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/limitations-of-the-client-portal-gateway) require browser authentication and API calls on the same machine. Its [FAQ](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq) requires daily browser reauthentication and says automated authentication is unsupported. The [API access FAQ](https://www.interactivebrokers.com/support/faq/content/get-api-access-629299016) describes manual gateway login with 2FA and notes that some authentication routes require approval/configuration.

[Gateway installation](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/installation-authentication) refers to a funded Pro account. The broader API FAQ describes fully open/funded clients more generally. Existing IBKR ownership alone does not establish the user's exact route eligibility.

### OAuth scope evidence

The [OAuth2 introduction](https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/introduction) frames access around licensed organizations, advisers, and IBrokers with designated scopes. The [broader migration overview](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/) discusses first-party and third-party OAuth use. These descriptions do not establish a particular retail account's available grant.

The [access-token example](https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/access-token) uses `sso-sessions.write`. No dedicated watchlist-only authorization scope was established in the material inspected. This is an evidence limitation, not proof that IBKR can never provide one. A request allowlist inside our application would restrict its implementation, not change the broker's token permissions.

## 5. Why TWS “watchlist data” is insufficient evidence

[Streaming Data](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data) describes `reqMktData` as quotes for a supplied contract. It does not document retrieving the saved membership of a user's watchlist. More decisively for strict data minimization, [Managed Accounts](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/managed-accounts) states that managed account IDs are delivered automatically on initial API connection.

## 6. Remaining integration questions

Before any optional live adapter, evidence is still needed for the exact enumeration method/parameter contract, the user's supported authorization route, its actual granted scope, initialization without prohibited account acquisition, and behavior alongside the user's existing brokerage session. These uncertainties concern broker integration; manual/file snapshot import and the wider research system do not depend on resolving them. Moving research to a server does not eliminate the chosen broker authentication route's session or daily-login requirements.
