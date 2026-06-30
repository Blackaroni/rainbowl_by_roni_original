const PAGE_SIZES = {
  customers: 8,
  products: 8,
  orders: 6,
  expenses: 8,
  accounts: 8,
};

const state = {
  dashboard: {
    total_sales: 0,
    total_paid: 0,
    total_outstanding: 0,
    pending_orders: 0,
    delivered_unpaid: 0,
  },
  customers: [],
  products: [],
  orders: [],
  expenses: [],
  accountSnapshots: [],
  monthlyInsights: {
    months: [],
  },
  nextCustomerId: "",
  orderFilters: {
    search: "",
    fulfillment_status: "",
    payment_status: "",
    date_from: "",
    date_to: "",
  },
  customerFilters: {
    search: "",
    location: "",
  },
  productFilters: {
    search: "",
    min_price: "",
    max_price: "",
  },
  expenseFilters: {
    search: "",
    category: "",
    date_from: "",
    date_to: "",
  },
  accountFilters: {
    search: "",
    date_from: "",
    date_to: "",
  },
  pagination: {
    customers: { page: 1, pageSize: PAGE_SIZES.customers },
    products: { page: 1, pageSize: PAGE_SIZES.products },
    orders: { page: 1, pageSize: PAGE_SIZES.orders },
    expenses: { page: 1, pageSize: PAGE_SIZES.expenses },
    accounts: { page: 1, pageSize: PAGE_SIZES.accounts },
  },
  orderEditId: null,
  customerEditId: null,
  productEditId: null,
  productViewId: null,
};

const API_BASE_URL = normalizeApiBaseUrl(window.RAINBOWL_CONFIG?.apiBaseUrl);

const currency = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  minimumFractionDigits: 2,
});

const dateTimeFormatter = new Intl.DateTimeFormat("en-NG", {
  dateStyle: "medium",
  timeStyle: "short",
});

const monthFormatter = new Intl.DateTimeFormat("en-NG", {
  month: "long",
  year: "numeric",
});

document.addEventListener("DOMContentLoaded", async () => {
  bindNavigation();
  bindForms();
  bindFilterControls();
  resetOrderForm();
  resetCustomerForm();
  resetProductForm();
  await refreshAllData();
});

async function refreshAllData() {
  try {
    const [dashboard, customers, nextCustomerId, products, orders, expenses, accountSnapshots, monthlyInsights] = await Promise.all([
      api("/api/dashboard"),
      api("/api/customers"),
      api("/api/customers/next-id"),
      api("/api/products"),
      api("/api/orders"),
      api("/api/expenses"),
      api("/api/account-snapshots"),
      api("/api/insights/monthly"),
    ]);

    state.dashboard = dashboard;
    state.customers = customers;
    state.nextCustomerId = nextCustomerId.next_customer_id || "";
    state.products = products;
    state.orders = orders;
    state.expenses = expenses;
    state.accountSnapshots = accountSnapshots;
    state.monthlyInsights = monthlyInsights;

    if (state.productEditId && !state.products.some((product) => product.id === state.productEditId)) {
      resetProductForm();
    }
    if (state.productViewId && !state.products.some((product) => product.id === state.productViewId)) {
      state.productViewId = null;
    }

    renderDashboard();
    renderCustomerOptions();
    renderProductOptions();
    renderCustomerIdField();
    renderFilterOptionSets();
    renderCustomersTable();
    renderProductDetailCard();
    renderProductsTable();
    renderOrdersList();
    renderExpensesTable();
    renderAccountSnapshotsTable();
    renderInsights();
    recalculateOrderSummary();
  } catch (error) {
    showToast(error.message, true);
  }
}

function bindNavigation() {
  document.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.view).classList.add("active");
    });
  });
}

function bindForms() {
  document.getElementById("add-item-row").addEventListener("click", () => {
    addOrderItemRow();
    recalculateOrderSummary();
  });

  document.getElementById("cancel-order-edit").addEventListener("click", () => {
    resetOrderForm();
  });

  document.getElementById("cancel-customer-edit").addEventListener("click", () => {
    resetCustomerForm();
  });

  document.getElementById("cancel-product-edit").addEventListener("click", () => {
    resetProductForm();
  });

  document.getElementById("clear-order-filters").addEventListener("click", clearOrderFilters);
  document.getElementById("clear-customer-filters").addEventListener("click", clearCustomerFilters);
  document.getElementById("clear-product-filters").addEventListener("click", clearProductFilters);
  document.getElementById("clear-expense-filters").addEventListener("click", clearExpenseFilters);
  document.getElementById("clear-account-filters").addEventListener("click", clearAccountFilters);

  document.getElementById("order-form").addEventListener("submit", handleOrderSubmit);
  document.getElementById("customer-form").addEventListener("submit", handleCustomerSubmit);
  document.getElementById("product-form").addEventListener("submit", handleProductSubmit);
  document.getElementById("expense-form").addEventListener("submit", handleExpenseSubmit);
  document.getElementById("account-form").addEventListener("submit", handleAccountSubmit);
}

function bindFilterControls() {
  bindFilterInput("order-filter-search", "input", (value) => {
    state.orderFilters.search = value.trim();
    resetPagination("orders");
    renderOrdersList();
  });
  bindFilterInput("order-filter-fulfillment-status", "change", (value) => {
    state.orderFilters.fulfillment_status = value;
    resetPagination("orders");
    renderOrdersList();
  });
  bindFilterInput("order-filter-payment-status", "change", (value) => {
    state.orderFilters.payment_status = value;
    resetPagination("orders");
    renderOrdersList();
  });
  bindFilterInput("order-filter-date-from", "change", (value) => {
    state.orderFilters.date_from = value;
    resetPagination("orders");
    renderOrdersList();
  });
  bindFilterInput("order-filter-date-to", "change", (value) => {
    state.orderFilters.date_to = value;
    resetPagination("orders");
    renderOrdersList();
  });

  bindFilterInput("customers-search", "input", (value) => {
    state.customerFilters.search = value.trim();
    resetPagination("customers");
    renderCustomersTable();
  });
  bindFilterInput("customers-location-filter", "change", (value) => {
    state.customerFilters.location = value;
    resetPagination("customers");
    renderCustomersTable();
  });

  bindFilterInput("products-search", "input", (value) => {
    state.productFilters.search = value.trim();
    resetPagination("products");
    renderProductsTable();
  });
  bindFilterInput("products-min-price", "input", (value) => {
    state.productFilters.min_price = value.trim();
    resetPagination("products");
    renderProductsTable();
  });
  bindFilterInput("products-max-price", "input", (value) => {
    state.productFilters.max_price = value.trim();
    resetPagination("products");
    renderProductsTable();
  });

  bindFilterInput("expenses-search", "input", (value) => {
    state.expenseFilters.search = value.trim();
    resetPagination("expenses");
    renderExpensesTable();
  });
  bindFilterInput("expenses-category-filter", "change", (value) => {
    state.expenseFilters.category = value;
    resetPagination("expenses");
    renderExpensesTable();
  });
  bindFilterInput("expenses-date-from", "change", (value) => {
    state.expenseFilters.date_from = value;
    resetPagination("expenses");
    renderExpensesTable();
  });
  bindFilterInput("expenses-date-to", "change", (value) => {
    state.expenseFilters.date_to = value;
    resetPagination("expenses");
    renderExpensesTable();
  });

  bindFilterInput("accounts-search", "input", (value) => {
    state.accountFilters.search = value.trim();
    resetPagination("accounts");
    renderAccountSnapshotsTable();
  });
  bindFilterInput("accounts-date-from", "change", (value) => {
    state.accountFilters.date_from = value;
    resetPagination("accounts");
    renderAccountSnapshotsTable();
  });
  bindFilterInput("accounts-date-to", "change", (value) => {
    state.accountFilters.date_to = value;
    resetPagination("accounts");
    renderAccountSnapshotsTable();
  });
}

function bindFilterInput(elementId, eventName, callback) {
  document.getElementById(elementId).addEventListener(eventName, (event) => {
    callback(event.target.value);
  });
}

async function handleOrderSubmit(event) {
  event.preventDefault();
  try {
    const payload = buildOrderPayload();
    if (state.orderEditId) {
      await api(`/api/orders/${state.orderEditId}`, {
        method: "PATCH",
        body: payload,
      });
      showToast("Order updated.");
    } else {
      await api("/api/orders", {
        method: "POST",
        body: payload,
      });
      showToast("Order saved.");
    }
    resetOrderForm();
    await refreshAllData();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function handleCustomerSubmit(event) {
  event.preventDefault();
  const payload = {
    name: document.getElementById("customer-name").value.trim(),
    phone_number: document.getElementById("customer-phone-number").value.trim(),
    location: document.getElementById("customer-location").value.trim(),
  };

  if (!payload.name) {
    showToast("Customer name is required.", true);
    return;
  }

  if (!state.customerEditId) {
    payload.legacy_customer_id = document.getElementById("customer-legacy-id").value.trim();
  }

  try {
    if (state.customerEditId) {
      await api(`/api/customers/${state.customerEditId}`, {
        method: "PATCH",
        body: payload,
      });
      showToast("Customer updated.");
    } else {
      await api("/api/customers", {
        method: "POST",
        body: payload,
      });
      showToast("Customer added.");
    }
    resetCustomerForm();
    await refreshAllData();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function handleProductSubmit(event) {
  event.preventDefault();
  const isEditing = Boolean(state.productEditId);
  const payload = {
    legacy_product_id: document.getElementById("product-legacy-id").value.trim(),
    name: document.getElementById("product-name").value.trim(),
    selling_price: Number(document.getElementById("product-selling-price").value),
    cost_price: Number(document.getElementById("product-cost-price").value),
  };

  if (!payload.name) {
    showToast("Product name is required.", true);
    return;
  }
  if (!Number.isFinite(payload.selling_price) || payload.selling_price < 0) {
    showToast("Selling price must be zero or more.", true);
    return;
  }
  if (!Number.isFinite(payload.cost_price) || payload.cost_price < 0) {
    showToast("Cost price must be zero or more.", true);
    return;
  }

  try {
    const product = isEditing
      ? await api(`/api/products/${state.productEditId}`, {
          method: "PATCH",
          body: payload,
        })
      : await api("/api/products", {
          method: "POST",
          body: payload,
        });
    state.productViewId = product.id;
    resetProductForm();
    await refreshAllData();
    showToast(isEditing ? "Product updated." : "Product added.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function handleExpenseSubmit(event) {
  event.preventDefault();
  const payload = {
    expense_date: document.getElementById("expense-date").value,
    expense_category: document.getElementById("expense-category").value.trim(),
    product_id: Number(document.getElementById("expense-product-id").value) || null,
    quantity: parseOptionalNumber(document.getElementById("expense-quantity").value),
    uom: document.getElementById("expense-uom").value.trim(),
    amount: Number(document.getElementById("expense-amount").value),
    description: document.getElementById("expense-description").value.trim(),
  };

  try {
    await api("/api/expenses", {
      method: "POST",
      body: payload,
    });
    event.target.reset();
    await refreshAllData();
    showToast("Expense added.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function handleAccountSubmit(event) {
  event.preventDefault();
  const payload = {
    snapshot_date: document.getElementById("account-date").value,
    opening_balance: parseOptionalNumber(document.getElementById("account-opening-balance").value) ?? 0,
    money_in: parseOptionalNumber(document.getElementById("account-money-in").value) ?? 0,
    money_out: parseOptionalNumber(document.getElementById("account-money-out").value) ?? 0,
  };

  try {
    await api("/api/account-snapshots", {
      method: "POST",
      body: payload,
    });
    event.target.reset();
    await refreshAllData();
    showToast("Account snapshot added.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function buildOrderPayload() {
  const customerId = Number(document.getElementById("order-customer").value);
  const orderDate = document.getElementById("order-date").value;
  const requestedCollectionDate = document.getElementById("order-collection-date").value;
  const fulfillmentStatus = document.getElementById("order-fulfillment-status").value;
  const notes = document.getElementById("order-notes").value.trim();
  const items = collectOrderItemsForSubmission();

  if (!customerId) {
    throw new Error("Customer is required.");
  }
  if (!orderDate) {
    throw new Error("Order date is required.");
  }
  if (!fulfillmentStatus) {
    throw new Error("Fulfillment status is required.");
  }
  if (!items.length) {
    throw new Error("Add at least one order item.");
  }

  const payload = {
    customer_id: customerId,
    order_date: orderDate,
    requested_collection_date: requestedCollectionDate || null,
    fulfillment_status: fulfillmentStatus,
    notes,
    items,
  };

  if (!state.orderEditId) {
    const initialPaymentValue = document.getElementById("order-initial-payment").value.trim();
    if (initialPaymentValue) {
      const initialPayment = Number(initialPaymentValue);
      const paymentMethod = document.getElementById("order-payment-method").value.trim();
      const paymentDate = document.getElementById("order-payment-date").value;
      if (!Number.isFinite(initialPayment) || initialPayment < 0) {
        throw new Error("Initial payment must be zero or more.");
      }
      if (initialPayment > 0 && !paymentMethod) {
        throw new Error("Payment method is required when recording an initial payment.");
      }
      if (initialPayment > 0 && !paymentDate) {
        throw new Error("Payment date is required when recording an initial payment.");
      }
      payload.initial_payment = initialPayment;
      if (initialPayment > 0) {
        payload.payment_method = paymentMethod;
        payload.payment_date = paymentDate;
      }
    }
  }

  return payload;
}

function renderDashboard() {
  document.getElementById("metric-total-sales").textContent = formatMoney(state.dashboard.total_sales);
  document.getElementById("metric-total-paid").textContent = formatMoney(state.dashboard.total_paid);
  document.getElementById("metric-outstanding").textContent = formatMoney(state.dashboard.total_outstanding);
  document.getElementById("badge-pending-orders").textContent = `Pending: ${state.dashboard.pending_orders}`;
  document.getElementById("badge-delivered-unpaid").textContent = `Delivered unpaid: ${state.dashboard.delivered_unpaid}`;
}

function renderCustomerOptions() {
  const customerSelect = document.getElementById("order-customer");
  const currentValue = customerSelect.value;
  customerSelect.innerHTML = ['<option value="">Select customer</option>']
    .concat(
      state.customers.map(
        (customer) =>
          `<option value="${customer.id}">${escapeHtml(customer.name)} (${escapeHtml(customer.legacy_customer_id || customer.id)})</option>`
      )
    )
    .join("");
  if (state.customers.some((customer) => String(customer.id) === currentValue)) {
    customerSelect.value = currentValue;
  }
}

function renderProductOptions() {
  const expenseSelect = document.getElementById("expense-product-id");
  const currentExpenseValue = expenseSelect.value;
  expenseSelect.innerHTML = ['<option value="">No linked product</option>']
    .concat(state.products.map((product) => `<option value="${product.id}">${escapeHtml(product.name)}</option>`))
    .join("");
  if (state.products.some((product) => String(product.id) === currentExpenseValue)) {
    expenseSelect.value = currentExpenseValue;
  }

  document.querySelectorAll(".item-product").forEach((select) => {
    const selectedValue = select.value;
    populateItemProductSelect(select, selectedValue);
  });
}

function renderCustomerIdField() {
  if (state.customerEditId) {
    return;
  }
  document.getElementById("customer-legacy-id").value = state.nextCustomerId || "";
}

function renderFilterOptionSets() {
  renderSelectFilterOptions(
    "customers-location-filter",
    "All locations",
    state.customerFilters.location,
    state.customers.map((customer) => customer.location).filter(Boolean)
  );
  renderSelectFilterOptions(
    "expenses-category-filter",
    "All categories",
    state.expenseFilters.category,
    state.expenses.map((expense) => expense.expense_category).filter(Boolean)
  );
}

function renderSelectFilterOptions(elementId, placeholder, selectedValue, values) {
  const select = document.getElementById(elementId);
  const uniqueValues = Array.from(new Set(values.map((value) => String(value).trim()).filter(Boolean))).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" })
  );
  select.innerHTML = [`<option value="">${escapeHtml(placeholder)}</option>`]
    .concat(uniqueValues.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
    .join("");
  if (selectedValue && uniqueValues.includes(selectedValue)) {
    select.value = selectedValue;
  } else if (selectedValue) {
    select.value = "";
    if (elementId === "customers-location-filter") {
      state.customerFilters.location = "";
    }
    if (elementId === "expenses-category-filter") {
      state.expenseFilters.category = "";
    }
  }
}

function renderCustomersTable() {
  const filteredCustomers = getFilteredCustomers();
  const paginated = paginateItems(filteredCustomers, "customers");
  const body = document.getElementById("customers-table-body");
  document.getElementById("customers-filter-summary").textContent = buildSummaryText(
    filteredCustomers.length,
    state.customers.length,
    "customer"
  );

  body.innerHTML = paginated.items.length
    ? paginated.items
        .map(
          (customer) => `
            <tr>
              <td>${escapeHtml(customer.legacy_customer_id || String(customer.id))}</td>
              <td>${escapeHtml(customer.name)}</td>
              <td>${escapeHtml(customer.phone_number || "-")}</td>
              <td>${escapeHtml(customer.location || "-")}</td>
              <td><button class="ghost-button compact-button edit-customer-button" data-customer-id="${customer.id}" type="button">Edit</button></td>
            </tr>
          `
        )
        .join("")
    : renderEmptyTableRow(5, "No customers match the current filters.");

  body.querySelectorAll(".edit-customer-button").forEach((button) => {
    button.addEventListener("click", () => {
      startCustomerEdit(Number(button.dataset.customerId));
    });
  });

  renderPagination("customers", "customers-pagination", filteredCustomers.length, paginated);
}

function renderProductsTable() {
  const filteredProducts = getFilteredProducts();
  const paginated = paginateItems(filteredProducts, "products");
  const body = document.getElementById("products-table-body");
  document.getElementById("products-filter-summary").textContent = buildSummaryText(
    filteredProducts.length,
    state.products.length,
    "product"
  );

  body.innerHTML = paginated.items.length
    ? paginated.items
        .map(
          (product) => `
            <tr>
              <td>${escapeHtml(product.legacy_product_id || String(product.id))}</td>
              <td>${escapeHtml(product.name)}</td>
              <td>${formatMoney(product.selling_price)}</td>
              <td>${formatMoney(product.cost_price)}</td>
              <td>
                <div class="table-action-row">
                  <button class="ghost-button compact-button view-product-button" data-product-id="${product.id}" type="button">View</button>
                  <button class="ghost-button compact-button edit-product-button" data-product-id="${product.id}" type="button">Edit</button>
                  <button class="danger-button compact-button delete-product-button" data-product-id="${product.id}" type="button">Delete</button>
                </div>
              </td>
            </tr>
          `
        )
        .join("")
    : renderEmptyTableRow(5, "No products match the current filters.");

  body.querySelectorAll(".view-product-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.productViewId = Number(button.dataset.productId);
      renderProductDetailCard();
    });
  });
  body.querySelectorAll(".edit-product-button").forEach((button) => {
    button.addEventListener("click", () => {
      startProductEdit(Number(button.dataset.productId));
    });
  });
  body.querySelectorAll(".delete-product-button").forEach((button) => {
    button.addEventListener("click", async () => {
      await deleteProduct(Number(button.dataset.productId));
    });
  });

  renderPagination("products", "products-pagination", filteredProducts.length, paginated);
}

function renderProductDetailCard() {
  const panel = document.getElementById("product-view-panel");
  const product = state.products.find((entry) => entry.id === state.productViewId);
  if (!product) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }

  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="section-heading">
      <div>
        <h4>${escapeHtml(product.name)}</h4>
        <p class="meta">Product details and quick actions.</p>
      </div>
      <div class="table-action-row">
        <button id="product-view-edit-button" class="ghost-button compact-button" type="button">Edit</button>
        <button id="product-view-delete-button" class="danger-button compact-button" type="button">Delete</button>
        <button id="product-view-close-button" class="ghost-button compact-button" type="button">Close</button>
      </div>
    </div>
    <div class="detail-grid">
      <div class="detail-item">
        <span>Product ID</span>
        <strong>${escapeHtml(product.legacy_product_id || String(product.id))}</strong>
      </div>
      <div class="detail-item">
        <span>Selling price</span>
        <strong>${formatMoney(product.selling_price)}</strong>
      </div>
      <div class="detail-item">
        <span>Cost price</span>
        <strong>${formatMoney(product.cost_price)}</strong>
      </div>
      <div class="detail-item">
        <span>Created</span>
        <strong>${escapeHtml(formatDateTime(product.created_at))}</strong>
      </div>
      <div class="detail-item">
        <span>Updated</span>
        <strong>${escapeHtml(formatDateTime(product.updated_at))}</strong>
      </div>
    </div>
  `;

  document.getElementById("product-view-edit-button").addEventListener("click", () => {
    startProductEdit(product.id);
  });
  document.getElementById("product-view-delete-button").addEventListener("click", async () => {
    await deleteProduct(product.id);
  });
  document.getElementById("product-view-close-button").addEventListener("click", () => {
    state.productViewId = null;
    renderProductDetailCard();
  });
}

function renderOrdersList() {
  const filteredOrders = getFilteredOrders();
  const paginated = paginateItems(filteredOrders, "orders");
  const list = document.getElementById("orders-list");
  document.getElementById("order-filter-summary").textContent = buildSummaryText(
    filteredOrders.length,
    state.orders.length,
    "order"
  );

  if (!paginated.items.length) {
    list.innerHTML = '<p class="meta">No orders match the current filters.</p>';
    renderPagination("orders", "orders-pagination", filteredOrders.length, paginated);
    return;
  }

  list.innerHTML = paginated.items
    .map(
      (order) => `
        <details class="order-card" data-order-id="${order.id}" open>
          <summary class="order-topline">
            <div class="order-heading">
              <strong>${escapeHtml(order.order_number)} | ${escapeHtml(order.customer_name)}</strong>
              <span class="meta">
                Order date ${escapeHtml(order.order_date)}
                ${order.requested_collection_date ? ` | Collect ${escapeHtml(order.requested_collection_date)}` : ""}
              </span>
            </div>
            <div class="order-summary-badges">
              <span class="meta">Total ${formatMoney(order.order_total)}</span>
              <span class="status-pill payment">${escapeHtml(capitalize(order.payment_status))}</span>
              <span class="status-pill fulfillment">${escapeHtml(capitalize(order.fulfillment_status))}</span>
            </div>
          </summary>

          <div class="order-card-body">
            <div class="order-actions">
              <button class="ghost-button compact-button edit-order-button" data-order-id="${order.id}" type="button">Edit order</button>
            </div>

            <ul class="order-items-list">
              ${order.items
                .map(
                  (item) => `
                    <li>
                      <span>${escapeHtml(item.product_name)} | ${item.quantity} x ${formatMoney(item.unit_price)}</span>
                      <span>${formatMoney(item.line_total)} | margin ${formatMoney(item.line_margin)}</span>
                    </li>
                  `
                )
                .join("")}
            </ul>

            <div class="order-inline-form stat-inline">
              <span class="meta">Paid ${formatMoney(order.amount_paid)}</span>
              <span class="meta">Balance ${formatMoney(order.balance_due)}</span>
              <span class="meta">Items ${order.items.length}</span>
            </div>

            <div class="order-inline-form">
              <div class="inline-group">
                <select class="order-status-select">
                  ${["pending", "processing", "ready", "delivered", "cancelled"]
                    .map(
                      (status) =>
                        `<option value="${status}" ${order.fulfillment_status === status ? "selected" : ""}>${capitalize(status)}</option>`
                    )
                    .join("")}
                </select>
                <input class="order-collection-date-input" type="date" value="${order.requested_collection_date || ""}" />
                <button class="pill-button save-status-button" type="button">Update status</button>
              </div>

              <div class="inline-group">
                <input class="payment-amount-input" type="number" step="0.01" min="0" placeholder="Payment amount" />
                <input class="payment-method-input" type="text" placeholder="Method" />
                <input class="payment-date-input" type="date" />
                <button class="pill-button add-payment-button" type="button">Add payment</button>
              </div>
            </div>

            ${renderOrderPayments(order)}
            ${order.notes ? `<p class="meta">${escapeHtml(order.notes)}</p>` : ""}
          </div>
        </details>
      `
    )
    .join("");

  list.querySelectorAll(".edit-order-button").forEach((button) => {
    button.addEventListener("click", () => {
      startOrderEdit(Number(button.dataset.orderId));
    });
  });

  list.querySelectorAll(".save-status-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".order-card");
      const orderId = Number(card.dataset.orderId);
      const fulfillmentStatus = card.querySelector(".order-status-select").value;
      const requestedCollectionDate = card.querySelector(".order-collection-date-input").value;
      try {
        await api(`/api/orders/${orderId}`, {
          method: "PATCH",
          body: {
            fulfillment_status: fulfillmentStatus,
            requested_collection_date: requestedCollectionDate || null,
          },
        });
        await refreshAllData();
        showToast("Order updated.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });

  list.querySelectorAll(".add-payment-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".order-card");
      const orderId = Number(card.dataset.orderId);
      const amount = Number(card.querySelector(".payment-amount-input").value || 0);
      const method = card.querySelector(".payment-method-input").value.trim();
      const paymentDate = card.querySelector(".payment-date-input").value;
      if (!amount) {
        showToast("Enter a payment amount.", true);
        return;
      }
      if (!method) {
        showToast("Enter a payment method.", true);
        return;
      }
      if (!paymentDate) {
        showToast("Enter a payment date.", true);
        return;
      }
      try {
        await api(`/api/orders/${orderId}/payments`, {
          method: "POST",
          body: {
            amount,
            method,
            payment_date: paymentDate,
          },
        });
        await refreshAllData();
        showToast("Payment recorded.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });

  renderPagination("orders", "orders-pagination", filteredOrders.length, paginated);
}

function renderOrderPayments(order) {
  if (!order.payments || !order.payments.length) {
    return "";
  }
  return `
    <div class="detail-card">
      <h4>Payments</h4>
      <div class="detail-grid">
        ${order.payments
          .map(
            (payment) => `
              <div class="detail-item">
                <span>${escapeHtml(payment.payment_date)} | ${escapeHtml(payment.method)}</span>
                <strong>${formatMoney(payment.amount)}</strong>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderExpensesTable() {
  const filteredExpenses = getFilteredExpenses();
  const paginated = paginateItems(filteredExpenses, "expenses");
  const body = document.getElementById("expenses-table-body");
  document.getElementById("expenses-filter-summary").textContent = buildSummaryText(
    filteredExpenses.length,
    state.expenses.length,
    "expense"
  );

  body.innerHTML = paginated.items.length
    ? paginated.items
        .map(
          (expense) => `
            <tr>
              <td>${escapeHtml(expense.expense_date)}</td>
              <td>${escapeHtml(expense.expense_category)}</td>
              <td>${escapeHtml(expense.product_name || "-")}</td>
              <td>${escapeHtml(expense.description || "-")}</td>
              <td>${escapeHtml(expense.quantity || "-")} ${escapeHtml(expense.uom || "")}</td>
              <td>${formatMoney(expense.amount)}</td>
            </tr>
          `
        )
        .join("")
    : renderEmptyTableRow(6, "No expenses match the current filters.");

  renderPagination("expenses", "expenses-pagination", filteredExpenses.length, paginated);
}

function renderAccountSnapshotsTable() {
  const filteredSnapshots = getFilteredAccountSnapshots();
  const paginated = paginateItems(filteredSnapshots, "accounts");
  const body = document.getElementById("accounts-table-body");
  document.getElementById("accounts-filter-summary").textContent = buildSummaryText(
    filteredSnapshots.length,
    state.accountSnapshots.length,
    "snapshot"
  );

  body.innerHTML = paginated.items.length
    ? paginated.items
        .map(
          (snapshot) => `
            <tr>
              <td>${escapeHtml(snapshot.snapshot_date)}</td>
              <td>${formatMoney(snapshot.opening_balance)}</td>
              <td>${formatMoney(snapshot.money_in)}</td>
              <td>${formatMoney(snapshot.money_out)}</td>
              <td>${formatMoney(snapshot.balance)}</td>
            </tr>
          `
        )
        .join("")
    : renderEmptyTableRow(5, "No account snapshots match the current filters.");

  renderPagination("accounts", "accounts-pagination", filteredSnapshots.length, paginated);
}

function renderInsights() {
  renderMonthlyFinanceInsights();
  renderMonthlyProductInsights();
}

function renderMonthlyFinanceInsights() {
  const container = document.getElementById("insights-finance-grid");
  const months = state.monthlyInsights.months || [];
  if (!months.length) {
    container.innerHTML = '<p class="meta">No monthly data yet. Add orders, payments, and expenses to populate this view.</p>';
    return;
  }

  const maxValue = Math.max(
    1,
    ...months.map((month) => Math.max(month.total_sales, month.total_expenses, Math.abs(month.cash_in_account)))
  );

  container.innerHTML = months
    .map(
      (month) => `
        <article class="insight-card">
          <div class="section-heading">
            <div>
              <h3>${escapeHtml(formatMonthLabel(month.month))}</h3>
              <p class="meta">Gross sales, expenses, and cash position for the month.</p>
            </div>
          </div>
          <div class="insight-metrics">
            <div class="insight-metric">
              <span>Total sales</span>
              <strong>${formatMoney(month.total_sales)}</strong>
            </div>
            <div class="insight-metric">
              <span>Total paid</span>
              <strong>${formatMoney(month.total_paid)}</strong>
            </div>
            <div class="insight-metric">
              <span>Total expenses</span>
              <strong>${formatMoney(month.total_expenses)}</strong>
            </div>
            <div class="insight-metric">
              <span>Cash in account</span>
              <strong>${formatMoney(month.cash_in_account)}</strong>
            </div>
          </div>
          <div class="insight-bar-list">
            ${renderInsightBarRow("Sales", month.total_sales, maxValue, "sales")}
            ${renderInsightBarRow("Expenses", month.total_expenses, maxValue, "expenses")}
            ${renderInsightBarRow("Cash in account", month.cash_in_account, maxValue, "cash")}
          </div>
        </article>
      `
    )
    .join("");
}

function renderMonthlyProductInsights() {
  const container = document.getElementById("insights-products-grid");
  const months = state.monthlyInsights.months || [];
  if (!months.length) {
    container.innerHTML = '<p class="meta">No product sales yet. Saved orders will appear here by month.</p>';
    return;
  }

  container.innerHTML = months
    .map((month) => {
      const products = month.products || [];
      const maxValue = Math.max(1, ...products.map((product) => product.total_sales));
      return `
        <article class="insight-card">
          <div class="section-heading">
            <div>
              <h3>${escapeHtml(formatMonthLabel(month.month))}</h3>
              <p class="meta">${products.length} product${products.length === 1 ? "" : "s"} sold in this month.</p>
            </div>
          </div>
          ${
            products.length
              ? `
                <div class="insight-product-list">
                  ${products
                    .map(
                      (product) => `
                        <div class="insight-bar-row">
                          <div class="insight-bar-label">
                            <span>${escapeHtml(product.product_name)} | Qty ${product.quantity_sold}</span>
                            <span>${formatMoney(product.total_sales)} | margin ${formatMoney(product.total_margin)}</span>
                          </div>
                          <div class="insight-bar-track">
                            <div class="insight-bar-fill sales" style="width: ${product.total_sales ? Math.max(6, (product.total_sales / maxValue) * 100) : 0}%"></div>
                          </div>
                        </div>
                      `
                    )
                    .join("")}
                </div>
              `
              : '<p class="meta">No product sales recorded for this month.</p>'
          }
        </article>
      `;
    })
    .join("");
}

function getFilteredCustomers() {
  return state.customers.filter((customer) => {
    const matchesSearch = matchesWildcardSearch(state.customerFilters.search, [
      customer.legacy_customer_id,
      customer.id,
      customer.name,
      customer.phone_number,
      customer.location,
    ]);
    const matchesLocation = !state.customerFilters.location || customer.location === state.customerFilters.location;
    return matchesSearch && matchesLocation;
  });
}

function getFilteredProducts() {
  const minPrice = parseOptionalNumber(state.productFilters.min_price);
  const maxPrice = parseOptionalNumber(state.productFilters.max_price);
  return state.products.filter((product) => {
    const sellingPrice = Number(product.selling_price || 0);
    const matchesSearch = matchesWildcardSearch(state.productFilters.search, [
      product.legacy_product_id,
      product.id,
      product.name,
      product.selling_price,
      product.cost_price,
    ]);
    const matchesMin = minPrice == null || sellingPrice >= minPrice;
    const matchesMax = maxPrice == null || sellingPrice <= maxPrice;
    return matchesSearch && matchesMin && matchesMax;
  });
}

function getFilteredOrders() {
  return state.orders.filter((order) => {
    const matchesSearch = matchesWildcardSearch(state.orderFilters.search, [
      order.customer_name,
      order.order_number,
      order.notes,
      ...order.items.map((item) => item.product_name),
    ]);
    const matchesFulfillment =
      !state.orderFilters.fulfillment_status || order.fulfillment_status === state.orderFilters.fulfillment_status;
    const matchesPayment = !state.orderFilters.payment_status || order.payment_status === state.orderFilters.payment_status;
    const matchesDate = isWithinDateRange(order.order_date, state.orderFilters.date_from, state.orderFilters.date_to);
    return matchesSearch && matchesFulfillment && matchesPayment && matchesDate;
  });
}

function getFilteredExpenses() {
  return state.expenses.filter((expense) => {
    const matchesSearch = matchesWildcardSearch(state.expenseFilters.search, [
      expense.expense_date,
      expense.expense_category,
      expense.product_name,
      expense.description,
      expense.quantity,
      expense.uom,
      expense.amount,
    ]);
    const matchesCategory = !state.expenseFilters.category || expense.expense_category === state.expenseFilters.category;
    const matchesDate = isWithinDateRange(expense.expense_date, state.expenseFilters.date_from, state.expenseFilters.date_to);
    return matchesSearch && matchesCategory && matchesDate;
  });
}

function getFilteredAccountSnapshots() {
  return state.accountSnapshots.filter((snapshot) => {
    const matchesSearch = matchesWildcardSearch(state.accountFilters.search, [
      snapshot.snapshot_date,
      snapshot.opening_balance,
      snapshot.money_in,
      snapshot.money_out,
      snapshot.balance,
    ]);
    const matchesDate = isWithinDateRange(snapshot.snapshot_date, state.accountFilters.date_from, state.accountFilters.date_to);
    return matchesSearch && matchesDate;
  });
}

function startCustomerEdit(customerId) {
  const customer = state.customers.find((entry) => entry.id === customerId);
  if (!customer) {
    showToast("Customer not found.", true);
    return;
  }
  state.customerEditId = customer.id;
  document.getElementById("customer-form-title").textContent = `Edit ${customer.name}`;
  document.getElementById("customer-submit-button").textContent = "Update customer";
  document.getElementById("cancel-customer-edit").classList.remove("hidden");
  document.getElementById("customer-legacy-id").value = customer.legacy_customer_id || "";
  document.getElementById("customer-name").value = customer.name || "";
  document.getElementById("customer-phone-number").value = customer.phone_number || "";
  document.getElementById("customer-location").value = customer.location || "";
  document.getElementById("customer-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetCustomerForm() {
  state.customerEditId = null;
  document.getElementById("customer-form").reset();
  document.getElementById("customer-form-title").textContent = "New customer";
  document.getElementById("customer-submit-button").textContent = "Save customer";
  document.getElementById("cancel-customer-edit").classList.add("hidden");
  renderCustomerIdField();
}

function startProductEdit(productId) {
  const product = state.products.find((entry) => entry.id === productId);
  if (!product) {
    showToast("Product not found.", true);
    return;
  }
  state.productEditId = product.id;
  state.productViewId = product.id;
  document.getElementById("product-form-title").textContent = `Edit ${product.name}`;
  document.getElementById("product-submit-button").textContent = "Update product";
  document.getElementById("cancel-product-edit").classList.remove("hidden");
  document.getElementById("product-legacy-id").value = product.legacy_product_id || "";
  document.getElementById("product-name").value = product.name || "";
  document.getElementById("product-selling-price").value = product.selling_price ?? "";
  document.getElementById("product-cost-price").value = product.cost_price ?? "";
  renderProductDetailCard();
  document.getElementById("product-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetProductForm() {
  state.productEditId = null;
  document.getElementById("product-form").reset();
  document.getElementById("product-form-title").textContent = "Add product";
  document.getElementById("product-submit-button").textContent = "Save product";
  document.getElementById("cancel-product-edit").classList.add("hidden");
}

async function deleteProduct(productId) {
  const product = state.products.find((entry) => entry.id === productId);
  if (!product) {
    showToast("Product not found.", true);
    return;
  }
  const confirmed = window.confirm(`Delete ${product.name}? This cannot be undone.`);
  if (!confirmed) {
    return;
  }

  try {
    await api(`/api/products/${productId}`, { method: "DELETE" });
    if (state.productEditId === productId) {
      resetProductForm();
    }
    if (state.productViewId === productId) {
      state.productViewId = null;
    }
    await refreshAllData();
    showToast("Product deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function startOrderEdit(orderId) {
  const order = state.orders.find((entry) => entry.id === orderId);
  if (!order) {
    showToast("Order not found.", true);
    return;
  }

  state.orderEditId = order.id;
  document.getElementById("order-form-section").open = true;
  document.getElementById("order-form-title").textContent = `Edit ${order.order_number}`;
  document.getElementById("order-form-mode-copy").textContent = "Correct the order details here. Payments remain in the order list below.";
  document.getElementById("order-submit-button").textContent = "Update order";
  document.getElementById("cancel-order-edit").classList.remove("hidden");
  document.querySelectorAll(".create-only-field").forEach((field) => field.classList.add("hidden"));

  document.getElementById("order-customer").value = String(order.customer_id);
  document.getElementById("order-date").value = order.order_date || "";
  document.getElementById("order-collection-date").value = order.requested_collection_date || "";
  document.getElementById("order-fulfillment-status").value = order.fulfillment_status || "";
  document.getElementById("order-notes").value = order.notes || "";
  document.getElementById("order-initial-payment").value = "";
  document.getElementById("order-payment-method").value = "";
  document.getElementById("order-payment-date").value = "";

  clearOrderItems();
  order.items.forEach((item) => addOrderItemRow(item));
  ensureOrderItemRow();
  recalculateOrderSummary();
  document.getElementById("order-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetOrderForm() {
  state.orderEditId = null;
  document.getElementById("order-form").reset();
  document.getElementById("order-form-title").textContent = "New order";
  document.getElementById("order-form-mode-copy").textContent = "All fields start blank. Pick products and the app will fill the locked prices.";
  document.getElementById("order-submit-button").textContent = "Save order";
  document.getElementById("cancel-order-edit").classList.add("hidden");
  document.querySelectorAll(".create-only-field").forEach((field) => field.classList.remove("hidden"));
  clearOrderItems();
  ensureOrderItemRow();
  recalculateOrderSummary();
}

function addOrderItemRow(item = null) {
  const container = document.getElementById("order-items");
  const row = document.createElement("div");
  row.className = "item-row";
  row.innerHTML = `
    <label>
      Product
      <select class="item-product"></select>
    </label>
    <label>
      Qty
      <input class="item-quantity" type="number" min="0.01" step="0.01" placeholder="Enter quantity" />
    </label>
    <label>
      Selling price
      <input class="item-price readonly-field" type="number" min="0" step="0.01" readonly />
    </label>
    <label>
      Cost price
      <input class="item-cost readonly-field" type="number" min="0" step="0.01" readonly />
    </label>
    <label>
      Discount type
      <select class="item-discount-type">
        <option value="">No discount</option>
        <option value="amount">Amount</option>
        <option value="percent">Percent</option>
        <option value="none">None</option>
      </select>
    </label>
    <label>
      Discount value
      <input class="item-discount-value" type="number" min="0" step="0.01" placeholder="Optional" />
    </label>
    <button type="button" class="remove-item ghost-button">Remove</button>
  `;
  container.appendChild(row);

  const select = row.querySelector(".item-product");
  populateItemProductSelect(select, item ? String(item.product_id) : "");
  if (item) {
    row.querySelector(".item-quantity").value = item.quantity ?? "";
    row.querySelector(".item-price").value = item.unit_price ?? "";
    row.querySelector(".item-cost").value = item.unit_cost ?? "";
    row.querySelector(".item-discount-type").value = item.discount_type === "none" ? "none" : item.discount_type || "";
    row.querySelector(".item-discount-value").value = item.discount_value ? item.discount_value : "";
  }

  bindOrderItemRow(row);
}

function bindOrderItemRow(row) {
  const productField = row.querySelector(".item-product");
  productField.addEventListener("change", () => {
    applyProductDefaults(row);
    recalculateOrderSummary();
  });

  row.querySelectorAll("input, select").forEach((field) => {
    if (field === productField) {
      return;
    }
    field.addEventListener("input", () => {
      recalculateOrderSummary();
    });
    field.addEventListener("change", () => {
      recalculateOrderSummary();
    });
  });

  row.querySelector(".remove-item").addEventListener("click", () => {
    row.remove();
    ensureOrderItemRow();
    recalculateOrderSummary();
  });
}

function ensureOrderItemRow() {
  const container = document.getElementById("order-items");
  if (!container.children.length) {
    addOrderItemRow();
  }
}

function clearOrderItems() {
  document.getElementById("order-items").innerHTML = "";
}

function populateItemProductSelect(select, selectedValue = "") {
  select.innerHTML = ['<option value="">Select product</option>']
    .concat(
      state.products.map(
        (product) =>
          `<option value="${product.id}" data-selling-price="${product.selling_price}" data-cost-price="${product.cost_price}">
            ${escapeHtml(product.name)}
          </option>`
      )
    )
    .join("");
  if (selectedValue && state.products.some((product) => String(product.id) === String(selectedValue))) {
    select.value = selectedValue;
  }
}

function applyProductDefaults(row) {
  const select = row.querySelector(".item-product");
  const option = select.selectedOptions[0];
  const priceField = row.querySelector(".item-price");
  const costField = row.querySelector(".item-cost");
  if (!option || !option.value) {
    priceField.value = "";
    costField.value = "";
    return;
  }
  priceField.value = option.dataset.sellingPrice || "";
  costField.value = option.dataset.costPrice || "";
}

function collectOrderItemsForSubmission() {
  return Array.from(document.querySelectorAll(".item-row")).reduce((items, row, index) => {
    const productIdValue = row.querySelector(".item-product").value;
    const quantityValue = row.querySelector(".item-quantity").value.trim();
    const unitPriceValue = row.querySelector(".item-price").value.trim();
    const unitCostValue = row.querySelector(".item-cost").value.trim();
    const discountTypeValue = row.querySelector(".item-discount-type").value;
    const discountValueRaw = row.querySelector(".item-discount-value").value.trim();
    const hasAnyValue = [productIdValue, quantityValue, discountTypeValue, discountValueRaw].some(Boolean);

    if (!hasAnyValue) {
      return items;
    }
    if (!productIdValue) {
      throw new Error(`Select a product for item ${index + 1}.`);
    }
    if (!quantityValue || Number(quantityValue) <= 0) {
      throw new Error(`Enter a valid quantity for item ${index + 1}.`);
    }
    if (!unitPriceValue || !unitCostValue) {
      throw new Error(`Product pricing is missing for item ${index + 1}. Re-select the product.`);
    }
    if (discountValueRaw && !discountTypeValue) {
      throw new Error(`Choose a discount type for item ${index + 1}, or clear the discount value.`);
    }

    items.push({
      product_id: Number(productIdValue),
      quantity: Number(quantityValue),
      unit_price: Number(unitPriceValue),
      unit_cost: Number(unitCostValue),
      discount_type: discountTypeValue || "none",
      discount_value: discountValueRaw ? Number(discountValueRaw) : 0,
    });
    return items;
  }, []);
}

function collectPreviewItems() {
  return Array.from(document.querySelectorAll(".item-row")).reduce((items, row) => {
    const productId = Number(row.querySelector(".item-product").value || 0);
    const quantity = Number(row.querySelector(".item-quantity").value || 0);
    const unitPrice = Number(row.querySelector(".item-price").value || 0);
    const unitCost = Number(row.querySelector(".item-cost").value || 0);
    if (!productId || quantity <= 0 || unitPrice < 0 || unitCost < 0) {
      return items;
    }
    items.push({
      quantity,
      unit_price: unitPrice,
      unit_cost: unitCost,
      discount_type: row.querySelector(".item-discount-type").value || "none",
      discount_value: Number(row.querySelector(".item-discount-value").value || 0),
    });
    return items;
  }, []);
}

function recalculateOrderSummary() {
  const totals = collectPreviewItems().reduce(
    (accumulator, item) => {
      const lineSubtotal = item.quantity * item.unit_price;
      const costTotal = item.quantity * item.unit_cost;
      const discountAmount =
        item.discount_type === "percent"
          ? lineSubtotal * (item.discount_value / 100)
          : item.discount_type === "amount"
            ? item.discount_value
            : 0;
      const clampedDiscount = Math.min(Math.max(discountAmount, 0), lineSubtotal);
      const lineTotal = lineSubtotal - clampedDiscount;
      accumulator.subtotal += lineSubtotal;
      accumulator.discount += clampedDiscount;
      accumulator.total += lineTotal;
      accumulator.margin += lineTotal - costTotal;
      return accumulator;
    },
    { subtotal: 0, discount: 0, total: 0, margin: 0 }
  );

  document.getElementById("summary-subtotal").textContent = formatMoney(totals.subtotal);
  document.getElementById("summary-discount").textContent = formatMoney(totals.discount);
  document.getElementById("summary-total").textContent = formatMoney(totals.total);
  document.getElementById("summary-margin").textContent = formatMoney(totals.margin);
}

function clearOrderFilters() {
  state.orderFilters = {
    search: "",
    fulfillment_status: "",
    payment_status: "",
    date_from: "",
    date_to: "",
  };
  document.getElementById("order-filter-search").value = "";
  document.getElementById("order-filter-fulfillment-status").value = "";
  document.getElementById("order-filter-payment-status").value = "";
  document.getElementById("order-filter-date-from").value = "";
  document.getElementById("order-filter-date-to").value = "";
  resetPagination("orders");
  renderOrdersList();
}

function clearCustomerFilters() {
  state.customerFilters = {
    search: "",
    location: "",
  };
  document.getElementById("customers-search").value = "";
  document.getElementById("customers-location-filter").value = "";
  resetPagination("customers");
  renderCustomersTable();
}

function clearProductFilters() {
  state.productFilters = {
    search: "",
    min_price: "",
    max_price: "",
  };
  document.getElementById("products-search").value = "";
  document.getElementById("products-min-price").value = "";
  document.getElementById("products-max-price").value = "";
  resetPagination("products");
  renderProductsTable();
}

function clearExpenseFilters() {
  state.expenseFilters = {
    search: "",
    category: "",
    date_from: "",
    date_to: "",
  };
  document.getElementById("expenses-search").value = "";
  document.getElementById("expenses-category-filter").value = "";
  document.getElementById("expenses-date-from").value = "";
  document.getElementById("expenses-date-to").value = "";
  resetPagination("expenses");
  renderExpensesTable();
}

function clearAccountFilters() {
  state.accountFilters = {
    search: "",
    date_from: "",
    date_to: "",
  };
  document.getElementById("accounts-search").value = "";
  document.getElementById("accounts-date-from").value = "";
  document.getElementById("accounts-date-to").value = "";
  resetPagination("accounts");
  renderAccountSnapshotsTable();
}

function resetPagination(key) {
  state.pagination[key].page = 1;
}

function paginateItems(items, key) {
  const pagination = state.pagination[key];
  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pagination.pageSize));
  pagination.page = Math.min(Math.max(1, pagination.page), totalPages);
  const startIndex = (pagination.page - 1) * pagination.pageSize;
  const endIndex = startIndex + pagination.pageSize;
  return {
    items: items.slice(startIndex, endIndex),
    currentPage: pagination.page,
    totalPages,
    start: totalItems ? startIndex + 1 : 0,
    end: totalItems ? Math.min(endIndex, totalItems) : 0,
  };
}

function renderPagination(key, containerId, totalItems, paginated) {
  const container = document.getElementById(containerId);
  if (!totalItems) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = `
    <div class="pagination-summary">Showing ${paginated.start}-${paginated.end} of ${totalItems}</div>
    <div class="pagination-controls">
      <button class="pagination-button" data-page-action="prev" type="button" ${paginated.currentPage === 1 ? "disabled" : ""}>Previous</button>
      <span class="pagination-summary">Page ${paginated.currentPage} of ${paginated.totalPages}</span>
      <button class="pagination-button" data-page-action="next" type="button" ${paginated.currentPage === paginated.totalPages ? "disabled" : ""}>Next</button>
    </div>
  `;

  container.querySelectorAll(".pagination-button").forEach((button) => {
    button.addEventListener("click", () => {
      const delta = button.dataset.pageAction === "next" ? 1 : -1;
      state.pagination[key].page += delta;
      if (key === "customers") {
        renderCustomersTable();
      }
      if (key === "products") {
        renderProductsTable();
      }
      if (key === "orders") {
        renderOrdersList();
      }
      if (key === "expenses") {
        renderExpensesTable();
      }
      if (key === "accounts") {
        renderAccountSnapshotsTable();
      }
    });
  });
}

function buildSummaryText(filteredCount, totalCount, singularWord) {
  const totalWord = totalCount === 1 ? singularWord : `${singularWord}s`;
  if (filteredCount === totalCount) {
    return `${filteredCount} ${filteredCount === 1 ? singularWord : `${singularWord}s`} shown`;
  }
  return `${filteredCount} of ${totalCount} ${totalWord} shown`;
}

function renderEmptyTableRow(columnCount, message) {
  return `<tr><td class="table-empty" colspan="${columnCount}">${escapeHtml(message)}</td></tr>`;
}

function matchesWildcardSearch(search, values) {
  const normalizedSearch = String(search || "").trim();
  if (!normalizedSearch) {
    return true;
  }
  const haystacks = values.map((value) => String(value ?? "").toLowerCase());
  if (normalizedSearch.includes("*")) {
    const pattern = normalizedSearch
      .toLowerCase()
      .split("*")
      .map((part) => escapeRegex(part))
      .join(".*");
    const regex = new RegExp(pattern, "i");
    return haystacks.some((value) => regex.test(value));
  }
  const needle = normalizedSearch.toLowerCase();
  return haystacks.some((value) => value.includes(needle));
}

function isWithinDateRange(value, dateFrom, dateTo) {
  const normalized = String(value || "").slice(0, 10);
  if (!normalized) {
    return !dateFrom && !dateTo;
  }
  if (dateFrom && normalized < dateFrom) {
    return false;
  }
  if (dateTo && normalized > dateTo) {
    return false;
  }
  return true;
}

function renderInsightBarRow(label, value, maxValue, tone) {
  const numericValue = Number(value || 0);
  const width = numericValue ? Math.max(6, (Math.abs(numericValue) / maxValue) * 100) : 0;
  const toneClass = tone === "cash" && numericValue < 0 ? "cash negative" : tone;
  return `
    <div class="insight-bar-row">
      <div class="insight-bar-label">
        <span>${escapeHtml(label)}</span>
        <span>${formatMoney(value)}</span>
      </div>
      <div class="insight-bar-track">
        <div class="insight-bar-fill ${toneClass}" style="width: ${width}%"></div>
      </div>
    </div>
  `;
}

function formatMonthLabel(monthKey) {
  const [year, month] = String(monthKey || "").split("-");
  const parsed = new Date(Number(year), Number(month) - 1, 1);
  if (Number.isNaN(parsed.getTime())) {
    return String(monthKey || "");
  }
  return monthFormatter.format(parsed);
}

async function api(url, options = {}) {
  const response = await fetch(buildApiUrl(url), {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const contentType = response.headers.get("Content-Type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text().then((text) => ({ error: text.trim() }));
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status}).`);
  }
  return data;
}

function buildApiUrl(path) {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

function normalizeApiBaseUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

function parseOptionalNumber(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return null;
  }
  return Number(trimmed);
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.style.background = isError ? "rgba(143, 45, 45, 0.95)" : "rgba(22, 22, 22, 0.9)";
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => toast.classList.add("hidden"), 2800);
}

function formatMoney(value) {
  return currency.format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return dateTimeFormatter.format(parsed);
}

function capitalize(value) {
  return String(value).charAt(0).toUpperCase() + String(value).slice(1);
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
