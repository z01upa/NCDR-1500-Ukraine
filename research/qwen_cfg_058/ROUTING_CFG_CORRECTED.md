# NCDR-QWEN-CFG-058 — Формальна верифікація SH4 routing CFG
База: cee807c. Всі перевірки відтворено на реальному клоні; юніт-тести: `python3 research/qwen_cfg_058/test_sh4_semantics.py` → **ALL 5 PASSED** (реальний протокол запуску зафіксовано в цій сесії).

## КРИТИЧНА ПЕРЕВІРКА №1 — напрямок tst/bf (головне виправлення)
SH4: `tst Rn,R0` → T=1 якщо (Rn&R0)==0; `bf` taken ⇔ T==0 ⇔ біти **перетинаються**.
```
030ac1fc mov #0x1,r13        ; r13 = кандидатний біт (шляхом shad r1,r13 на 030ac1fe... так: 030ac1f8 mov #0x1,r13; 030ac1fa mov.l @(0x28,r15),r1; nop; 030ac1fe shad r1,r13 — delay-slot nop враховано)
030ac200 tst r13,r11
030ac202 bf 0x30ac1de
```
- Біт кандидата **встановлений** у r11 → T=0 → bf TAKEN → перехід на 0x30AC1DE (інкремент ітерації, кандидат **ПРОПУСКАЄТЬСЯ**).
- Біт **скинутий** → T=1 → NOT taken → fall-through 0x30AC204 → кандидат **ОБРОБЛЯЄТЬСЯ**.
**ПОВНИЙ РЕВЕРС** попередньої інтерпретації MASK-048/ROUTING-044: r11 є **EXCLUSION-маскою (списком заборон)**, а не allowlist. Встановлений біт = «не розширювати цей слот». Це узгоджується з усіма відомими мутаторами r11:
- 030ac1ce `or r4,r11` — ВСТАНОВЛЕННЯ біта слота після невдалої повторної перевірки суміжності (030ac1ca tst r1,r3 / bt 1d0) = додавання до заборон;
- 030ac356 `or r13,r11` — ВСТАНОВЛЕННЯ біта поточного кандидата при attrs-класі 9 (030ac350 cmp/eq #0x9) перед bra 1de = «ця гілка більше не обробляється» (термінація кандидата через заборону);
- 030ac100 `mov #0x0,r11` — порожня заборона на старті.
Отже семантика «set=forbid, clear=expand» CONFIRMED на трьох незалежних мутаторах + фільтрі. Назва «mask of allowed transitions» з ROUTING-044 — **REFUTED**; коректно: **transition-exclusion mask**.

## КРИТИЧНА ПЕРЕВІРКА №2 — таблиця 030AC160–166 (з delay slot)
```
030ac160 tst r8,r8      ; T1 = (r8==0)
030ac162 movt r3        ; r3 = T1
030ac164 tst r3,r3      ; T2 = (r3==0)
030ac166 bt/s 0x30ac188 ; taken ⇔ T2
030ac168 mov r3,@(0x24,r15)  ; DELAY SLOT — виконується ЗАВЖДИ
```
| r8 | T1 | r3 | T2 | bt/s | шлях | [sp+0x24] |
|----|----|----|----|------|------|-----------|
| 0  | 1  | 1  | 0  | NOT taken | 0x30ac16a: byte-table path | 1 |
| ≠0 | 0  | 0  | 1  | TAKEN    | 0x30ac188: bsr 0x30ac72c   | 0 |
CONFIRMED: **bsr 0x30AC72C виконується при r8≠0**, а байт-табличний шлях — при r8==0. Усі попередні звіті (ROUTING-044 «тільки коли r8==0») — **REFUTED** (помилка виникла через плутанину movt/T2 без повного ланцюжка). Прапорець [sp+0x24]=«r8==0» споживається пізніше: 030ac486–48a (`cmp/pl r7` шлях: tst r3,r3 / bf 0x30ac49e) та 030ac4e4–4e8 — впливає на вартість (+0x1F4=shll2*0x7d→+0x1F4? точно: 030ac4a4–aa додає 0x1F4 до @(0x28,r9) cost) — службовий прапорець режиму розширення.
Byte-table path детально: r12=0x30ac250-база; base=r12+[GBR+0x3A]*0x34+0x10; r11=zero-ext(byte [base+(GBR+0x3C)]) — 8-бітна exclusion-маска слотів 0..7 (бо цикл 030ac1ec обмежений [r12-струк+0x14]? індекс i йде до count). ac72c-path: r11=повернене r0 (32-бітне).

## КРИТИЧНА ПЕРЕВІРКА №3 — cmp/pl (030ac0a6)
Тестовано значення −2,−1,0,1,2,0x7FFFFFFF,0x80000000,0xFFFFFFFF: T=1 лише для строго >0. **bf taken для −2, −1, 0, 0x80000000, 0xFFFFFFFF** → 0x30ac0dc `exts.b r4,r5`; для >0 → 0x30ac0aa/0xac `mov #0x0,r5`. Отже гілка вибирається знаком *(global@0x30ac0c8)+0x50*, а «sentinel −2» НЕ доведений: −1 і 0 дають ту саму гілку (REFUTED як унікальний sentinel; CONFIRMED лише «non-positive → sign-extend path»). Тест у pytest: test_cmppl_strict.

## КРИТИЧНА ПЕРЕВІРКА №4 — аудит transition-гілок (витримки)
Усі bt/bf у 0x30AC04C перераховані зі скрипту; ключові:
- 030ac07a bf/s 0x30ac108 (після cmp/eq r4,[ctx+0x4]: спеціальний режим −2 у ctx+0x4) — delay `and r11,r8` виконується завжди;
- 030ac09e bf 0x30ac082 — пошук першого виставленого біта у слові [tab58+idx*0x58].word+4 (slot-scan);
- 030ac216 tst #0x1,r0 → bt 0x30ac2b8 (flag bit0 entry+0x30 → швидкий шлях зняття заборони);
- 030ac21a tst r2,r4 → bt 0x30ac260 (bit1);
- 030ac22c tst r5,r2 → bt 0x30ac2b4 (slot already forbidden in neighbor word);
- 030ac352 bf 0x30ac358 навколо or r13,r11: клас==9 → or виконується; інакше bra 1de без or... УВАГА: 030ac354 `bra 0x30ac1de` стоїть МІЖ 352 і 356; 356 `or r13,r11` — це **delay slot bra**, отже or виконується ЗАВЖДИ після bra 1de! Тобто кожен оброблений кандидат, що дійшов до 0x30AC354, отримує встановлення свого біта в r11 (унікальне відвідування слота). Клас 9 лише змінює маршрут прибуття (352 not-taken → 354). **MASK-048 твердження «OR direction needs check» закрито: OR unconditional on this exit path.** CONFIRMED via delay-slot rule.
- 0x02FFB9D4: підтверджено **bt/s 0x2ffba06** (рядок 74 asm-файлу), а не and #0x3f — помилка ROUTING-044 визнана; delay slot 02ffb9d6 `mov.b r0,@(0x10,GBR)` виконується завжди. Умова bt/s походить з 02ffb9c4–cc: `(u32[r7] >> 13) & 1 == 1` (shld #-0xd + and #1 + cmp/eq #1) — біт 13 слова edge+4/+5 (LE16 pair?) — конкретно: r7=RAM edge base, @r7 = u32 word+0, тобто disk bytes 0..3? Ні: r7 тут = запис із таблиці, поле +0x00; точне прив'язування до Section 5 UNKNOWN.

## ЕТАП 2 — producers r11 (повний список у 0x30AC04C)
1. 030ac100 `mov #0,r11` (init);
2. 030ac186 `extu.b r2,r11` (byte-table, r8==0);
3. 030ac192 `mov r0,r11` (результат ac72c, r8≠0);
4. 030ac1ce `or r4,r11` (додаткова заборона слота attrs&7);
5. 030ac356 `or r13,r11` (delay-slot, універсальне відзначення обробленого кандидата).
r11 ніде не AND-маскується і не скидається всередині функції → monotonically growing exclusion set. Стан кандидата: processed-біти більше не оброблюються (фільтр №1). Повторний обхід можливий лише через нові біти, встановлені мутаторами.

## Bit-accurate псевдокод ядра
```c
uint32_t forbid = 0;                                  // 030ac100
if (degree_field_signpositive) {                      // 030ac0a2-a8 (НЕ «==-2»)
  if (r8 != 0) forbid = ac72c(ctx, nbr, ...);         // 030ac188-192  [body UNKNOWN]
  else       forbid = u8 tbl[base0x34*r8ctx3A + 0x10 + ctx3C]; // 030ac16a-186
}
slot_of_cur = (attrs>>2)&0xF == 9 ? ... : attrs & 7;
if (bit(slot_of_cur, forbid)) {                       // 030ac1a6-1a8: SET -> skip extra check
  if (!bit(attrs&7, tab58_word4)) forbid |= 1<<slot;  // 030ac1ca-1ce
}
for (i=counter; i<count; i++) {                       // 030ac1ec-f2
  cand_bit = 1<<i;                                    // 030ac1f8-fe
  if (!(cand_bit & forbid)) goto next_candidate_via_204_process; // bf semantics fixed
  /* process candidate i */                           // 030ac204+
  ...flags/slot checks (030ac214-22c, 030ac27a-7c, 030ac2d2)...
exit_to_1de:                                          // 030ac354 + DELAY-SLOT or
  forbid |= cand_bit;   // always executed            // 030ac356
}
```
Увага: рядки 204-22c: після «process» кандидат може бути відхилений further branches; всі шляхи повернення до 1de проходять через 354/356 (перевірено: 030ac22e bra 354; 030ac2a6 bra 354; 030ac2e2 bra 354; 030ac30e bra 354; 030ac354 bra 1de). **Кожна оброблена ітерaція позначає свій біт у forbid** — механізм «visit-once», типовий для graph expansion.

## ЕТАП 3 — символьні сценарії (контрольний експеримент, аналітично)
- forbid=0: усі кандидати обробляються; після кожної ітерації their bits set → наступний прохід циклом їх пропускає.
- forbid=all-ones: жоден кандидат не обробляється, цикл лише інкрементує i до count → bra 0x30ac598 (вихід r0=[sp+0x20]).
- тільки біт i встановлений:Processing всех j≠i; i пропускається.
- граничний індекс: порівняння 030ac1f0 cmp/gt r1([sp+28]),r2([sp+14]) — кінець при i>=count.
- r11 змінюється тільки мутаторами 4,5; таблиця [tab58+idx*0x58].word4 модифікується на 030ac29e-a4 (`not/shad/and/mov.l @r7`) — **зняття біта сусіднього слота** після успішного переходу (динамічне оновлення adjacency!) — CONFIRMED store 030ac2a4 (delay slot bra 2aa).

## ЕТАП 4 — 0x30AC72C
Тіло недоступне: sh4_analysis.json містить лише метадані functions[] (va=51037996=0x30AC72C, end=0x30AC79E, reachable=57, calls=[], literals=[]), instructions[] порожній у опублікованому JSON. Файл 030ac72c.asm у routing/ відсутній. **Дизасемблювання не вигадувалося.** Точний діапазон для Codex: runtime VA 0x30AC72C–0x30AC79E; storage offset у ROM-образі = 0x0DB72C–0x0DB79E (image base 0x02FD1000→0x8CBF4000, sections.csv row NavigationRem.dll). Очікуваний доказ: чи повертає r0 32-бітну exclusion-маску (тоді обидва producerи однотипні).

## ЕТАП 5 — журнал помилок
1. ROUTING-044 «lower-6-bit extraction edge+5»: помилково приписано 02ffb9d4; реальна інструкція — bt/s; extraction #0x3f у тому місці не існує → твердження відкликано (REFUTED).
2. «bsr ac72c при r8==0»: реверсно (CHECK2) — при r8≠0.
3. «bf пропускає нульовий біт»: реверсно — bf пропускає встановлений біт (CHECK1).
4. «sentinel −2»: non-positive generic branch (CHECK3).
5. «or r13,r11 скидає/додає залежно від класу 9»: or виконується безумовно як delay slot bra (PEREVIRKA 4).
Наслідок для edge706: правила заповнення byte-table ([0x34*node]+[+0x3C], slot-біти) та таблиці 0x58 (word+4, word+0x54) залишаються **UNKNOWN** за змістом; відомо лише те, що new edge потребує коректних бітів у цих двох таблицях і що cover+0x10/+0x11 жодним доведеним шляхом не потрапляють у forbid-маску (ланцюг edge+4/+5 → routing decision: **розрив на кроці RAM-edge→tables; UNKNOWN**).

## ONE_NEXT_EXPERIMENT
Витягти 0x30AC72C–0x30AC79E (57 instr.) із локального образу (Codex, команда: `python extract_function.py --module NavigationRem.dll --va 0x30AC72C` за наявності reachable.jsonl.gz). Очікуваний доказ: форма mask-producer. Другий (без бінарника): диференційний replay на p-code v13 — вимкнути мутатор 030ac1ce та порівняти множини оброблених кандидатів; очікування: зникнення саме «second-pass slot forbids». Writer не змінено.
