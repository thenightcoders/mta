# 🎯 Updated Epics for Staff Money Transfer App

---

### EPIC 1 – Authentication & Role Management
- Implement login system with role-based access (Agent Abroad, Agent Burundi, Manager Abroad, Manager Burundi, Super Admin)
- Disable public registration; user creation handled by managers
- Allow managers to assign/remove roles to users
- Enforce strict permission rules per role (e.g., Agent Abroad cannot transfer funds)

---

### EPIC 2 – Transfer Workflow
- Agent Abroad declares a new transfer request (beneficiary info, amount, currency)
- Manager Abroad accepts and assigns Agent Burundi for execution
- Agent Burundi confirms completion (payout)
- Track and update transfer status (Pending, Completed, Rejected)
- Prevent duplicate execution or reassignment

---

### EPIC 3 – Commission System
- Define commission percentages at the transfer level
- Split commissions between:
  - Declaring Agent (Abroad)
  - Manager Abroad
  - Executing Agent (Burundi)
- Dashboard views for commission summaries by user and time period
- Commission logic must support dynamic percentage allocation

---

### EPIC 4 – Stock & Fund Management
- Manager Abroad manages foreign stock (deposits from agents, exchanges, transfers)
- Manager Abroad can perform internal transfer to Burundi stock (currency conversion required)
- Burundi stock is consumed upon delivery
- Implement exchange logic and maintain conversion history
- Ensure only managers can move or convert funds
- Real-time stock balance and history per currency/location

---

### EPIC 5 – Reporting & Financial Insights
- Exportable reports (CSV/XLS) for:
  - Transfers per day/week/month
  - Commission breakdowns
  - Stock movement history
- Visual analytics (charts, summaries)
- Filtering by user, role, currency, status

---

### EPIC 6 – User & Agent Management
- Manager features to:
  - Create/delete users
  - View agent activity and performance logs
  - Assign local managers or delegate stock control
- Track user actions (audit logs)

---

### EPIC 7 – Security, Audits & Logs
- Log all sensitive operations: transfers, deposits, assignments, exchanges
- Optional 2FA for manager login
- Admin view of full operation history
- Enforce permissions and validations at API level

---

### EPIC 8 – Notifications & Feedback
- Notify manager when a transfer is declared
- Notify Agent Burundi when a task is assigned
- Success/failure UI feedback on stock operations and role changes
