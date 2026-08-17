# MilkPasterization_Lib

Function block library for the milk pasteurization PLC program, authored in SCL and
loaded into the TIA Portal project `MCP_Server.ap20` (TIA Portal V20).

## Structure

```
src/FunctionBlocks/   SCL source for each function block (one .scl file per block)
```

## Blocks

| Block | Purpose |
| --- | --- |
| `FB_SoftStarter` | Switches a motor soft starter on/off with feedback supervision (start/stop latch, feedback timeout, fault latch with edge-triggered reset) |

## Deploying to TIA Portal

Blocks here are authored as plain SCL text so they're easy to review and diff in VS Code.
To bring a block into the TIA project, it needs to be generated from source inside TIA
Portal (Program blocks > External source files > add `.scl` file > right-click >
"Generate blocks from source"), or imported via the TIA MCP server's document-based
import once the block has been exported at least once in that format.

**Current blocker:** the `MCP_Server.ap20` project has no PLC device yet. The intended
CPU is a Siemens S7-1500 CPU 1515F-2 PN (order no. 6ES7 515-2FN03-0AB0, firmware V4.0),
named `MilkPasterization`. An automated insert via the MCP tooling failed (worker only
supports TIA Portal V21, this project is V20), so the device needs to be added manually
in TIA Portal before any blocks can be loaded.
