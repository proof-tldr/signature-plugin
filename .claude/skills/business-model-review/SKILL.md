---
name: business-model-review
description: Present a Signature domain model so non-technical business people can check it and spot what is wrong, as on the plugin's review page. Use when changing how the review page, or any other screen or text, shows a domain's things, relationships, calculations or rules to customers.
---

# Presenting a domain model for business review

The reviewer knows their business, not databases. Their job is to say whether Signature understood it correctly.
Show the model the way business experts validate one in fact-oriented modelling (Object-Role Modeling): as plain
facts they can judge, with real cases from their own data. The page lives in `plugins/signature/web/`; its model
code is `src/review.ts`, and the examples come from `server/src/signature_plugin/examples.py`.

## Read every relationship from every side

- A relationship is one fact between things, not a pointer from one to another. Read it from both sides: "Each
  order has exactly one customer." and "A customer can have any number of orders, including none." The model
  stores it on one side only; never let that storage choice decide the wording or the picture.
- Where the model says nothing about one side, say what Signature will assume ("any number, including none") so the
  reviewer can confirm or correct it.
- A thing related to itself reads once.
- Draw relationships without direction: no arrows, and an undirected layout, never left to right or top down,
  which imply a flow or hierarchy that is not there.

## Keep facts over three or more things whole

- A fact tying three or more things together ("the price a customer pays for a product in a region") is one
  sentence naming every thing. Splitting it into pairs loses what it says or invents facts that are not there.
- A thing whose records exist only to tie others together (an order line ties an order to a product) is shown as
  the fact it stands for, not as a thing of its own.
- Draw both as a small hub joined to each thing it involves.

## Ground everything in real cases

- Put a few real records beside each thing and a few real pairs beside each relationship, found on the customer's
  machine. People judge cases far better than general statements, and a wrong case is easy to spot.
- Calculations need real worked cases too (what this definition gives for last quarter); until Signature supplies a
  runnable query for each calculation, say what it is computed from in plain words.

## Use the reviewer's words

- No database vocabulary on the page: no tables, columns, types, schemas, keys, "entity" or "field". One quiet line
  may say where a thing's records come from ("From the orders table in your sales database").
- Kinds of value in plain words: Text, Number, Money, Date, Yes or no, "Can be empty".
- Labels say what they are ("What Signature knows about", "Rules Signature relies on"), not cryptic names ("Things",
  "Always true").
- Each item is marked Correct or Wrong. Wrong asks what is wrong with that item, in the reviewer's words, and counts
  as reviewed.
- Publishing asks first and says who will see it and that it can be corrected and published again.

## Check it

- The page's browser tests must keep passing, including the one that fails if database vocabulary reaches the page.
- After a visible change, run the `persona-review` skill on fresh screenshots before calling it done.
