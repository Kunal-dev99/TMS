"""The repository layer. Every query in the system lives here.

No service constructs a query, and nothing here holds a rule or does
arithmetic. tenant_id is filtered here rather than remembered in each
service, which is what makes real multi-tenancy a phase four change to this
package rather than an audit of every file.
"""
