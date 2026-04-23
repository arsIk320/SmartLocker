document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".password-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-target");
      const input = document.getElementById(targetId);
      if (!input) return;

      const nextType = input.type === "password" ? "text" : "password";
      input.type = nextType;
      button.textContent = nextType === "password" ? "👁" : "🙈";
    });
  });

  const menuToggle = document.querySelector("[data-menu-toggle]");
  const drawer = document.querySelector("[data-drawer]");
  const drawerBackdrop = document.querySelector("[data-menu-close]");

  const closeDrawer = () => {
    document.body.classList.remove("drawer-open");
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", "false");
    }
    if (drawer) {
      drawer.setAttribute("aria-hidden", "true");
      drawer.classList.remove("is-open");
    }
    if (drawerBackdrop) {
      drawerBackdrop.classList.remove("is-open");
    }
  };

  const openDrawer = () => {
    document.body.classList.add("drawer-open");
    if (menuToggle) {
      menuToggle.setAttribute("aria-expanded", "true");
    }
    if (drawer) {
      drawer.setAttribute("aria-hidden", "false");
      drawer.classList.add("is-open");
    }
    if (drawerBackdrop) {
      drawerBackdrop.classList.add("is-open");
    }
  };

  if (menuToggle && drawer) {
    const toggleDrawer = (event) => {
      if (event) {
        event.preventDefault();
      }
      const opened = document.body.classList.contains("drawer-open");
      if (opened) {
        closeDrawer();
      } else {
        openDrawer();
      }
    };

    menuToggle.addEventListener("click", toggleDrawer);
    menuToggle.addEventListener("touchstart", toggleDrawer, { passive: false });
  }

  if (drawerBackdrop) {
    drawerBackdrop.addEventListener("click", closeDrawer);
  }

  document.querySelectorAll(".app-drawer a").forEach((link) => {
    link.addEventListener("click", closeDrawer);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDrawer();
    }
  });
});
