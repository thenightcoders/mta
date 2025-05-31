# 📋 Functional Requirements

### 🔐 Authentication & Roles
- Only agents and managers can log in
- No public signup — users created by managers/admins
- Roles:
  - **Agent Abroad**: Declares transfers,  deposit funds to manager, view own history
  - **Agent Burundi**: Executes transfers (assigned)
  - **Manager Abroad**:	Holds stock abroad,  Oversees operations, assigns agents, receives deposits, operates transfers, assigns delivery agent
  - **Manager Burundi**: Holds local stock, confirms deliveries, manages local agents

  - **Super Admin**: (Optional) Oversees all
  Manager Burundi is just an Agent that holds local stock

### 💶 Stock Management
🏦 Stocks:
 - Abroad Stock (per manager abroad):
    - **Increased by** : Initial capital, deposits from agents
    - **Decreased by** : Transfers (assigned to Burundi), exchange operations

- Burundi Stock (per manager/local branch):
    - **Increased by**: Incoming internal transfer from Abroad
    - **Decreased by**: Payouts to receivers

🔄 Operations:
- Internal Transfer (abroad → Burundi): Performed by manager, applies exchange rate

- Exchange: Managers may convert between currencies to adjust stock balance

- Stock Report: View real-time or filtered stock history

### 🔄 Transfer Management (With Roles & Commission)

- Agent Abroad declares a transfer:
  - Recipient name, phone, amount, currency
  - Manager is auto-linked to the transfer
- Manager Abroad receives declaration, accepts transfer, assigns a Burundi agent to deliver
- Transfer marked as complete by Agent Burundi
- Track status: Pending, Completed, Rejected
- Commission is split:
     - Initial Agent
     - Manager Abroad
     - Agent Burundi

### 💱 Currency & Exchange
- Transfers accepted in EUR/USD/etc.
- Delivered in BIF/EUR/USD based on instruction
- Exchange rate is variable, editable by manager

### 💰 Commissions
- Commission % of total amount (can be set by manager)
- Commission is split between (can vary):
  - Declaring agent (abroad)
  - Manager
  - Executing agent (Burundi)

### 💼 Stock Management
- Stocks exist in:
  - **Abroad**: Managed by foreign managers
  - **Burundi**: Managed by local managers
- Stock events:
  - Transfer (reduces abroad stock, reduces Burundi stock)
  - Deposit by agent to manager (increases abroad stock)
  - Manual exchange (USD → BIF)
  - Inter-stock transfer (abroad → Burundi)
- Manager can view history of stock inflow/outflow

### 🔐 Security & Workflow Rules

- Only managers handle withdrawals & internal fund movements

- Agents only act within their permissions (no stock transfers)

- Every operation is logged (who/when/how much)

### 👥 User Management
- Manager can:
  - Add/remove agents
  - Assign roles
  - View agent activity logs

### 📈 Reporting & Dashboard
- Daily/Weekly/Monthly transfer reports
- Total commissions earned (per agent, manager)
- Stock evolution over time
- Export to Excel/CSV

### 🔒 Logs & Security
- Log all stock movements, transfer edits, user actions
- 2FA optional for managers
- Role-based permissions enforced in all APIs
