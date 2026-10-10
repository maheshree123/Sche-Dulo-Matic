# Interview notes: Sche-Dulo-Matic
(Keep this file private; don't push it to GitHub.)

**30-second pitch.** "I built a timetable generator and a web portal around it. The college office publishes a clash-free timetable;
teachers sign up, get approved, and see their lectures and classes. If a teacher needs a different time, they send a request. It only
offers slots that don't clash, the office approves or declines, and approval moves the lecture in the live timetable.
It's Flask and SQLite with hand-written HTML/CSS, and 47 tests."

## The engine
**Q: Which OOP concepts did you use?** Classes and objects (`Teacher`, `Room`, `Subject`, `Division`, `Timetable`), encapsulation (each
object keeps its own `busy` set), inheritance (`LabRoom(Room)`), and polymorphism via the `kind` attribute.

**Q: How do you prevent clashes?** Teachers, rooms and classes each have a set of `(day, slot)` keys. Before booking, every set is
checked; only then are all of them updated. Sets give O(1) lookups.

**Q: Is it optimal?** No. Greedy with randomized restarts: hardest sessions (labs) first, least-loaded day first, retry on failure.
A solver (OR-Tools) would be exact. Impossible demands are reported, never hidden.

## The web app
**Q: Walk me through a change request.** The teacher clicks a lecture. The server computes every `(day, slot, room)` the lecture could
move to (`available_moves`), using the same rules as the generator. On submit I validate again on the server, because the browser can be tampered with.
The office sees the request with a live `check_move`. On approve I re-check and then update the session in one transaction.

**Q: Why re-check at approval time?** The timetable may have changed since the request was made (another approved move can take the slot).
Re-checking guarantees the stored timetable never contains a clash. A test proves it.

**Q: How do you handle authentication?** Passwords are hashed with Werkzeug (scrypt) and never stored. On login I clear the session
(prevents session fixation), unknown emails take the same time as wrong passwords, and the message is identical. Accounts need office
approval, and approval status is checked on every request, so a revoked teacher loses access immediately.

**Q: What about authorization?** A decorator checks the role on every route (403 for the wrong role). Teachers can only open request forms for
their own lectures (404 otherwise). Tests cover each of these.

**Q: CSRF?** A random token is stored in the session and must be in every POST form, compared in constant time. My own test found a bug in my first
version: a client with no session token could send an empty token and pass. Now a missing token is rejected.

**Q: Other security measures?** Parameterised SQL, Jinja auto-escaping (a test posts a `<script>` message and checks it's escaped),
a Content-Security-Policy that allows no scripts, X-Frame-Options, HttpOnly/SameSite cookies, upload size limit, uploads parsed as JSON only.

**Q: What would you add before going live?** HTTPS with secure cookies, login rate limiting, password reset by email, email notifications,
audit logging, and a managed database.

**Q: Why SQLite?** Zero setup and plenty for one college. The access layer is plain SQL, so moving to PostgreSQL/MySQL is straightforward.

**Q: Why no JavaScript?** Server-rendered pages are simpler, faster and safer; forms and links cover every workflow. The styled radio buttons
are pure CSS. JS could be added later for drag-and-drop editing.

**Q: How did you design the UI?** A small design system in one CSS file: variables for colours, light and dark themes via `prefers-color-scheme`,
consistent cards, badges and buttons, a responsive grid, and a deterministic colour per subject (golden-angle hues so neighbours look different).
I checked every page in a real browser, including mobile, and fixed what I found (a macro name shadowing the data, cell padding, the mobile nav).

**Q: How did you test it?** 47 tests: the engine, the move rules, and the web flow with Flask's test client (sign-up and approval, permissions,
CSRF, request approve/decline, a slot taken meanwhile, republishing, invalid uploads, XSS). I also ran the whole flow in a headless browser.

**Q: Hardest part?** (Say your own story. Good options: keeping move validation identical between the generator and the live timetable,
or deciding what happens to pending requests when the timetable is regenerated: they expire with an explanation.)
