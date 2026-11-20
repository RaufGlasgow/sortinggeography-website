// CLDR text for one site language (Story 18.4): the launch date, the chip
// date, the Lisbon time and country names, from Node's built-in ICU/CLDR, so
// no translator ever types a date or a country name.
//   node scripts/cldr.mjs <lang> <release_ms> [ISO2 ...]   -> JSON on stdout
const [lang, msArg, ...isos] = process.argv.slice(2);
const ms = Number(msArg);
const loc = lang === 'en' ? 'en-GB' : lang;
const tz = 'Europe/Lisbon';
const d = new Date(ms);
const fmt = (o) => new Intl.DateTimeFormat(loc, { timeZone: tz, ...o }).format(d);
const names = new Intl.DisplayNames([loc], { type: 'region' });
console.log(JSON.stringify({
  date: fmt({ day: 'numeric', month: 'long', year: 'numeric' }),
  chip: fmt({ day: 'numeric', month: 'long' }),
  lisbon: fmt({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
  utc: new Intl.DateTimeFormat(loc, { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d),
  countries: Object.fromEntries(isos.map((i) => [i, names.of(i)])),
}));
