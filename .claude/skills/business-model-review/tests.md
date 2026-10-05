# business-model-review: test requests

## Should load the skill

1. "Add a section to the review page for the customer's suppliers and how they relate to products."
   Works when: the relationship reads from both sides, the diagram stays undirected, real example pairs are shown,
   and no database words appear.
2. "Show calculations with an example on the review page."
   Works when: it asks for real worked cases from the customer's data and notes that this needs a runnable query from
   Signature for each calculation.
3. "Signature now returns a price that depends on customer, product and region; show it."
   Works when: it is one sentence naming all three and drawn as a hub, not split into pairs.

## Should not load the skill

- "Fix the DuckDB lockdown in local_data.py." (local query execution, not presentation).
- "Change the API key prompt in plugin.json." (installation, not the review).
