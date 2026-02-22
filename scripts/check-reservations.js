#!/usr/bin/env node
/**
 * Gastropub Reservation Monitor
 * Checks OpenTable + Resy for available slots at Jake's shortlisted spots.
 * Dates: 2026-02-28, 2026-03-01, 2026-03-02, 2026-03-04, 2026-03-06
 * Party size: 2
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, 'reservation-state.json');

const RESTAURANTS = [
  {
    name: 'The Marksman',
    area: 'Shoreditch',
    platform: 'opentable',
    url: 'https://www.opentable.co.uk/r/the-marksman-hackney-london',
  },
  {
    name: 'The Marksman',
    area: 'Shoreditch',
    platform: 'resy',
    slug: 'marksman-public-house',
  },
  {
    name: 'The Princess of Shoreditch',
    area: 'Shoreditch',
    platform: 'opentable',
    url: 'https://www.opentable.co.uk/the-princess-of-shoreditch',
  },
  {
    name: 'The Royal Oak Marylebone',
    area: 'Marylebone',
    platform: 'resy',
    slug: 'the-royal-oak-marylebone',
  },
];

const DATES = [
  '2026-02-28',
  '2026-03-01',
  '2026-03-02',
  '2026-03-04',
  '2026-03-06',
];

const PARTY_SIZE = 2;
const PREFERRED_TIME = '19:00'; // 7pm default

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return { found: {}, lastRun: null };
  }
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function slotKey(restaurant, date, times) {
  return `${restaurant.name}|${restaurant.platform}|${date}|${times.sort().join(',')}`;
}

async function checkOpenTable(page, restaurant, date) {
  const dateTime = `${date}T${PREFERRED_TIME}`;
  const url = `${restaurant.url}?covers=${PARTY_SIZE}&dateTime=${dateTime}`;
  
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // Extra wait for JS to render
    await page.waitForTimeout(5000);
    
    // Wait for time slots to appear
    await page.waitForSelector('[data-test="time-slot"], button[class*="timeslot"], button[class*="time-slot"], [class*="TimeSlot"], a[class*="slot"]', {
      timeout: 15000
    }).catch(() => null);

    // Extract available times
    const slots = await page.evaluate(() => {
      const selectors = [
        '[data-test="time-slot"]',
        'button[class*="timeslot"]',
        'button[class*="TimeSlot"]',
        '[class*="timeslot-button"]',
        'a[class*="time-slot"]',
      ];
      
      for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
          return Array.from(els)
            .filter(el => !el.disabled && !el.classList.toString().includes('unavailable'))
            .map(el => el.textContent.trim())
            .filter(t => t.length > 0);
        }
      }
      
      // Fallback: look for any text that looks like a time
      const allText = document.body.innerText;
      const timeMatches = allText.match(/\b\d{1,2}:\d{2}\s*(AM|PM|am|pm)?\b/g);
      return timeMatches ? [...new Set(timeMatches)] : [];
    });

    return slots;
  } catch (err) {
    console.error(`  [OpenTable] Error checking ${restaurant.name} on ${date}: ${err.message}`);
    return [];
  }
}

async function checkResy(page, restaurant, date) {
  const url = `https://resy.com/cities/lon/${restaurant.slug}?date=${date}&seats=${PARTY_SIZE}`;
  
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(5000);
    
    // Wait for time slots
    await page.waitForSelector('[class*="ReservationButton"], [class*="time-slot"], button[class*="slot"], [data-test*="slot"]', {
      timeout: 15000
    }).catch(() => null);

    const slots = await page.evaluate(() => {
      const selectors = [
        '[class*="ReservationButton"]',
        'button[class*="slot"]',
        '[data-test*="time-slot"]',
        '[class*="timeslot"]',
        'li[class*="time"] button',
      ];
      
      for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
          return Array.from(els)
            .filter(el => !el.disabled)
            .map(el => el.textContent.trim())
            .filter(t => /\d{1,2}:\d{2}/.test(t));
        }
      }
      return [];
    });

    return slots;
  } catch (err) {
    console.error(`  [Resy] Error checking ${restaurant.name} on ${date}: ${err.message}`);
    return [];
  }
}

async function main() {
  const state = loadState();
  const newFindings = [];

  console.log(`\n🍺 Gastropub Reservation Check — ${new Date().toISOString()}`);
  console.log(`Checking ${RESTAURANTS.length} restaurants × ${DATES.length} dates...\n`);

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-http2',
      '--disable-blink-features=AutomationControlled',
      '--disable-dev-shm-usage',
    ],
  });

  try {
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      locale: 'en-GB',
      timezoneId: 'Europe/London',
      viewport: { width: 1280, height: 800 },
      extraHTTPHeaders: {
        'Accept-Language': 'en-GB,en;q=0.9',
      },
    });

    // Hide webdriver property
    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    });

    const page = await context.newPage();

    for (const restaurant of RESTAURANTS) {
      for (const date of DATES) {
        process.stdout.write(`  Checking ${restaurant.name} (${restaurant.platform}) on ${date}... `);

        let slots = [];
        if (restaurant.platform === 'opentable') {
          slots = await checkOpenTable(page, restaurant, date);
        } else if (restaurant.platform === 'resy') {
          slots = await checkResy(page, restaurant, date);
        }

        if (slots.length > 0) {
          const key = `${restaurant.name}|${restaurant.platform}|${date}`;
          const existing = state.found[key] || [];
          const newSlots = slots.filter(s => !existing.includes(s));

          if (newSlots.length > 0 || existing.length === 0) {
            newFindings.push({
              restaurant: restaurant.name,
              area: restaurant.area,
              platform: restaurant.platform,
              date,
              slots,
              isNew: newSlots.length > 0,
            });
            state.found[key] = slots;
          }

          console.log(`✅ ${slots.length} slot(s): ${slots.join(', ')}`);
        } else {
          console.log('❌ None');
        }

        // Small delay to be polite
        await page.waitForTimeout(2000);
      }
    }
  } finally {
    await browser.close();
  }

  state.lastRun = new Date().toISOString();
  saveState(state);

  if (newFindings.length > 0) {
    console.log('\n🎉 NEW AVAILABILITY FOUND:\n');
    for (const f of newFindings) {
      const dateLabel = new Date(f.date).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
      console.log(`  🍽️  ${f.restaurant} (${f.area}) — ${dateLabel}`);
      console.log(`     Platform: ${f.platform}`);
      console.log(`     Times: ${f.slots.join(', ')}`);
      console.log();
    }
    // Output summary for cron notification
    process.stdout.write('\nNOTIFY:');
    const summary = newFindings.map(f => {
      const dateLabel = new Date(f.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
      return `${f.restaurant} on ${dateLabel} (${f.slots.join('/')}) via ${f.platform}`;
    }).join('; ');
    console.log(summary);
  } else {
    console.log('\nNo new availability found.');
    console.log('NOTIFY:none');
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
