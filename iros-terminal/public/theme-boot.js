(function () {
  try {
    var t = localStorage.getItem("iros-desk-theme");
    if (t !== "light" && t !== "dark") {
      t = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    var f = localStorage.getItem("iros-desk-font");
    if (f !== "sm" && f !== "md" && f !== "lg" && f !== "xl") f = "md";
    document.documentElement.setAttribute("data-theme", t);
    document.documentElement.setAttribute("data-font", f);
    document.documentElement.style.colorScheme = t;
  } catch (e) {}
})();
