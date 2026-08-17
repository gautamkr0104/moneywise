// Toggle transaction form fields based on the selected type.
(function () {
  var typeSelect = document.getElementById("txn-type");
  if (!typeSelect) {
    return;
  }
  function sync() {
    var isTransfer = typeSelect.value === "transfer";
    var toAccountField = document.getElementById("field-to-account");
    var categoryField = document.getElementById("field-category");
    var accountLabel = document.querySelector(
      "#field-account label"
    );
    if (toAccountField) {
      toAccountField.style.display = isTransfer ? "" : "none";
    }
    if (categoryField) {
      categoryField.style.display = isTransfer ? "none" : "";
    }
    if (accountLabel) {
      accountLabel.textContent = isTransfer ? "From account" : "Account";
    }
  }
  typeSelect.addEventListener("change", sync);
  sync();
})();
