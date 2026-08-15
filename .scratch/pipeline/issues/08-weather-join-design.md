# 08 Weather join design

Type: grilling
Status: open
Blocked by: 02, 03

## Question

How precip attaches to bus observations: at what key (H3 cell-hour vs point sample),
from which store per epoch (AORC historical vs MRMS near-real-time, per ticket 02),
via which bridge (per ticket 03), and the lag structure (precip in trailing 15/60/180
min windows, antecedent wetness). Also where the join runs: inside the streaming job
(broadcast grid) vs a batch feature table the streaming output joins later. Output of
this ticket is the feature spec the analysis stands on.
