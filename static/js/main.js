/**
 * Auction Ethiopia LMS — Main JavaScript
 */
document.addEventListener('DOMContentLoaded', function () {
  var sidebar = document.getElementById('sidebar');
  var backdrop = document.getElementById('sidebar-backdrop');
  var themeToggle = document.getElementById('themeToggle');

  // Dark Mode Toggle
  function initTheme() {
    var savedTheme = localStorage.getItem('theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
      document.documentElement.setAttribute('data-bs-theme', 'dark');
      if (themeToggle) {
        themeToggle.innerHTML = '<i class="bi bi-sun"></i>';
      }
    } else {
      document.documentElement.setAttribute('data-bs-theme', 'light');
      if (themeToggle) {
        themeToggle.innerHTML = '<i class="bi bi-moon"></i>';
      }
    }
  }

  function toggleTheme() {
    var currentTheme = document.documentElement.getAttribute('data-bs-theme');
    var newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-bs-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    if (themeToggle) {
      themeToggle.innerHTML = newTheme === 'dark' ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon"></i>';
    }
  }

  if (themeToggle) {
    themeToggle.addEventListener('click', toggleTheme);
  }

  initTheme();

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('show');
    if (backdrop) backdrop.classList.remove('show');
    document.body.classList.remove('sidebar-open');
  }

  function openSidebar() {
    if (sidebar) sidebar.classList.add('show');
    if (backdrop) backdrop.classList.add('show');
    document.body.classList.add('sidebar-open');
  }

  document.querySelectorAll('[data-sidebar-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (sidebar && sidebar.classList.contains('show')) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });
  });

  if (backdrop) {
    backdrop.addEventListener('click', closeSidebar);
  }

  document.querySelectorAll('.sidebar-nav-link').forEach(function (link) {
    link.addEventListener('click', function () {
      if (window.innerWidth < 992) {
        closeSidebar();
      }
    });
  });

  document.querySelectorAll('.alert-dismissible').forEach(function (alert) {
    setTimeout(function () {
      var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 5000);
  });
});
