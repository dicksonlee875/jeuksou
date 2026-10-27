# Jeuksou 著數碼: promo code wallet updater

A Python script that reads public promo-code pages every few days, adds any new codes to your wallet and expires old ones. Then it builds the 著數碼 page in English, 繁體中文 and 简体中文. It doesn't use Claude or any other AI.

```
sources.json        the pages to read (add or remove pages here)
data/deals.json     every code: the 119 already in the wallet plus anything new the scraper finds
data/perks.json     card perks for the Perks tab (Visa Infinite, World Elite, Amex Platinum…), edited by hand
data/programs.json  hotel and airline programmes for the Perks tab: tiers, point transfers, status links (edited by hand)
scraper.py          fetches the pages, finds codes and end dates, updates data/deals.json
build.py            turns data/deals.json into public/index.html (the wallet page)
template.html       the page design (style, layout, the three languages)
icons/              the home-screen app icon
update.sh / .bat    runs both scripts in one go
.github/workflows/  runs everything on GitHub every 3 days and publishes the page
```

## Run it on your computer

You need Python 3.9 or newer.

```
pip install -r requirements.txt
python scraper.py        # read the pages and update the codes
python build.py          # write public/index.html
```

Open `public/index.html` in any browser. It works offline, and on a phone you can save it to your home screen.

Useful options:

- `python scraper.py --dry-run` shows what would be added without saving anything.
- `python scraper.py --file saved_page.html --site klook` tests the code finder on a page you saved from your browser.

## Add it to your phone's home screen

Once the page has a web link (see Option A below, `https://<project-name>.pages.dev`), open it on your phone:

- **iPhone (Safari):** tap Share, then **Add to Home Screen**.
- **Android (Chrome):** tap **⋮**, then **Add to Home screen** or **Install app**.

It shows up as **Jeuksou** with the 著 icon and opens full screen.

## Update every 3 days automatically

### Option A: GitHub + Cloudflare Pages (recommended, free, your computer can stay off)

1. Create a **private** repository on github.com and upload everything in this folder, including the hidden `.github` folder.
2. Go to **Actions**, open **Update Jeuksou** and press **Run workflow** once to check it works.
3. Sign up at dash.cloudflare.com (free). Go to **Workers & Pages → Create → Pages → Connect to Git**, pick the repository, leave the build command empty and set the output folder to `public`.

From then on GitHub runs the update at 09:00 Hong Kong time every 3 days and saves the new codes and page. Cloudflare publishes each update at `https://<project-name>.pages.dev` within about a minute. To change how often it runs, edit the `cron` line in `.github/workflows/update.yml`. For example, `0 1 */2 * *` runs every 2 days and `0 1 * * 1,4` runs on Mondays and Thursdays.

Why these two: a private repository gets 2,000 free Actions minutes a month (this uses about 20), and GitHub only pauses schedules in public repositories. Cloudflare Pages has no bandwidth limit on static pages and allows commercial use, so ads or affiliate links later are fine.

If a run goes red, every page failed to load (a network problem or blocked requests). The live page stays as it was until the next run.

### Option B: Mac or Linux (cron)

Run `crontab -e` and add this line, changing the path to where you put this folder:

```
0 9 */3 * * /path/to/promo-scraper/update.sh >> /path/to/promo-scraper/update.log 2>&1
```

### Option C: Windows (Task Scheduler)

1. Open **Task Scheduler** and click **Create Basic Task**.
2. Set the trigger to **Daily** and **Recur every 3 days**.
3. Set the action to **Start a program** and pick `update.bat` in this folder.

## How the scraper decides what's a code

- A code is a 5 to 20 character word in capitals that mixes letters and digits (like `HSBC26H`) or is 6+ capital letters (like `WELCOMEHK`). It has to sit next to words like *code*, *coupon*, *promo*, 優惠碼 or 折扣碼, or be shown in bold or on a copy button.
- It reads the discount (`15%`, `HK$50`, `9折`) and the end date from the same line. It understands `2026-11-30`, `30/11/2026`, `30 Nov 2026`, `Nov 30, 2026`, `2026年11月30日` and `11月30日`.
- New codes go in as **Unconfirmed** with an **Auto-found** tag. Their description is the original text from the page, so a Chinese page gives a Chinese description in every language.
- Codes already in the wallet are never rewritten. The scraper only notes the date it last saw them.
- Any code past its end date becomes **Expired**. An auto-found code that no page has listed for 21 days becomes Expired too.

## Fixing things by hand

`data/deals.json` is plain text. Open it in any editor to:

- correct an auto-found code: change `status` to `active`, `restricted` or `avoid`, and rewrite `title`, `desc`, `cond` (plus `title_zh`, `desc_zh`, `cond_zh` for Chinese)
- delete a fake code: remove its `{ ... }` block
- change a region's top 10: edit the lists under `regions` (`world`, `hk`, `jp`, `kr`, `tw`, `sg`, `uk`, `eu`, `us`). Each category lists site keys best first, at most 10. A new region also needs its name in `regions` in both language blocks of `template.html`
- add a new shop: add it under `sites` with a `name`, `note`, `note_zh` and `color`, then add its page to `sources.json`

Only fill in 繁體 (`_zh`) fields. `build.py` converts them to 简体 automatically. If a mainland word comes out wrong, add it to `PHRASES` in `build.py`.

`data/perks.json` holds the card perks. The scraper never touches it, so check each perk's `url` still opens the right page now and then, update `checked`, and run `python build.py`.

## Limits worth knowing

- **It follows each site's robots.txt** and identifies itself as JeuksouBot. Pages that ask bots to stay away are skipped and show as "blocked by robots.txt".

- **It finds fewer codes than a person would.** Some sites hide codes behind a "Show code" button, load them with JavaScript, or block scripts entirely. Those pages show up as failed (✗) or return 0 codes. Add a different page for that shop in `sources.json`.
- **It can't test codes at checkout.** That needs a logged-in account and a real cart. Tap **Worked** or **Didn't work** in the wallet after you try one.
- **Entries marked `avoid` (fake codes, company-only rate numbers) stay in `deals.json` but are left off the page.** Use `python build.py --keep-avoid` to see them.
- **Codes from card-only and region-only deals still have those rules.** Check the conditions before you rely on a code.
- Source pages change their layout over time. If a page that used to give codes starts giving 0, open it in a browser and check that the codes are still in the page text.
- The dealhack.com pages for Europcar, Avis, Hertz, Expedia and Hotels.com in `sources.json` follow the same URL pattern as the working ones, but they weren't checked. Remove any that keep failing.
