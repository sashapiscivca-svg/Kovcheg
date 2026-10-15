# Responsible use

[Українська](RESPONSIBLE_USE.uk.md)

Kovcheg exists so that people cut off from the internet can still reach the knowledge they need: how to stop bleeding, how to make water safe, how to restart a generator, what a medication label means. We built it to run on the cheapest hardware so that shelters, volunteer groups, rural clinics and families can use it, not only well-funded organisations.

## What Kovcheg is, and what it is not

- **It is a library assistant.** It searches the documents **you** put in and shows the passages with their exact location. An optional language model summarises those passages with citations.
- **It is not a doctor, an engineer or an emergency service.** It knows nothing beyond your documents, and a small language model can misread them.
- **It is only as good as its library.** Outdated, wrong or unofficial documents produce outdated, wrong or unofficial answers. Prefer official, current protocols from recognised bodies (for example ministries of health, the Red Cross / Red Crescent, WHO, civil protection services).

## Rules for safe use in an emergency

1. **If you can reach emergency services, contact them.** Use Kovcheg while you wait, or when you cannot reach them.
2. **Read the cited source before acting**, especially for doses, intervals, voltages, pressures and any irreversible step. The source text is authoritative, not the generated answer.
3. **"Not found" means "not in this library"**, not "it does not exist" or "it is safe".
4. **Prefer search-only mode** (no language model) when time allows. You read the original passages directly.
5. **Check integrity.** Use modules marked valid or unsigned that you built yourself. Do not use modules marked INVALID.

## Uses we ask you to avoid

The MIT licence does not restrict use. We ask, without legal force, that Kovcheg not be used to plan or cause harm to people, to target or surveil people, or to spread content designed to deceive people in a crisis.

## For people who build libraries for others

- Record where each document came from and its date in the module description.
- Sign the modules you distribute (`kovcheg sign`) and publish your public key through a channel your users trust.
- Test typical questions (`kovcheg eval`) before distributing a module. Add a short "how to use" note for non-technical users.
- Respect copyright and licences of the documents you include.

## Reporting problems

If Kovcheg gave a dangerous or misleading answer, please report it (see [SECURITY.md](SECURITY.md)) together with the question, the module and, if possible, the documents involved. These reports directly improve the safety of the system.
