/**
 * Ethiopian Calendar (ዓውደ አውራኅ / E.C.) Client-Side Real-Time Conversion & Form Synchronization.
 * Zero-dependency, mathematically exact bidirectional synchronization.
 */

(function () {
  'use strict';

  const ETHIOPIAN_MONTHS_EN = [
    'Meskerem', 'Tikimt', 'Hidar', 'Tahsas', 'Tir', 'Yakatit',
    'Magabit', 'Miyazya', 'Ginbot', 'Sene', 'Hamle', 'Nehase', 'Pagume'
  ];

  const ETHIOPIAN_MONTHS_AM = [
    'መስከረም', 'ጥቅምት', 'ኅዳር', 'ታኅሣሥ', 'ጥር', 'የካቲት',
    'መጋቢት', 'ሚያዝያ', 'ግንቦት', 'ሰኔ', 'ሐምሌ', 'ነሐሴ', 'ጳጉሜ'
  ];

  const ETHIOPIC_EPOCH_ORDINAL = 2796;

  // Convert JS Date to Python ordinal (days since 0001-01-01)
  function dateToOrdinal(year, month, day) {
    const a = Math.floor((14 - month) / 12);
    const y = year + 4800 - a;
    const m = month + 12 * a - 3;
    const jdn = day + Math.floor((153 * m + 2) / 5) + 365 * y + Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400) - 32045;
    // Gregorian 0001-01-01 is JDN 1721426, so ordinal = jdn - 1721425
    return jdn - 1721425;
  }

  function ordinalToDate(ordinal) {
    const jdn = ordinal + 1721425;
    const a = jdn + 32044;
    const b = Math.floor((4 * a + 3) / 146097);
    const c = a - Math.floor((146097 * b) / 4);
    const d = Math.floor((4 * c + 3) / 1461);
    const e = c - Math.floor((1461 * d) / 4);
    const m = Math.floor((5 * e + 2) / 153);
    const day = e - Math.floor((153 * m + 2) / 5) + 1;
    const month = m + 3 - 12 * Math.floor(m / 10);
    const year = 100 * b + d - 4800 + Math.floor(m / 10);
    return { year, month, day };
  }

  function isEthiopianLeapYear(year) {
    return (year % 4) === 3;
  }

  function daysInEthiopianMonth(year, month) {
    if (month >= 1 && month <= 12) return 30;
    if (month === 13) return isEthiopianLeapYear(year) ? 6 : 5;
    return 30;
  }

  function gregorianToEthiopian(year, month, day) {
    const days = dateToOrdinal(year, month, day) - ETHIOPIC_EPOCH_ORDINAL;
    if (days < 0) return null;

    const cycle = Math.floor(days / 1461);
    const rem = days % 1461;

    let yearInCycle, dayInYear;
    if (rem < 365) {
      yearInCycle = 1;
      dayInYear = rem;
    } else if (rem < 730) {
      yearInCycle = 2;
      dayInYear = rem - 365;
    } else if (rem < 1096) {
      yearInCycle = 3;
      dayInYear = rem - 730;
    } else {
      yearInCycle = 4;
      dayInYear = rem - 1096;
    }

    const ethYear = 4 * cycle + yearInCycle;
    const ethMonth = Math.floor(dayInYear / 30) + 1;
    const ethDay = (dayInYear % 30) + 1;

    return { year: ethYear, month: ethMonth, day: ethDay };
  }

  function ethiopianToGregorian(ethYear, ethMonth, ethDay) {
    if (ethYear < 1 || ethMonth < 1 || ethMonth > 13) return null;
    const maxDays = daysInEthiopianMonth(ethYear, ethMonth);
    if (ethDay < 1 || ethDay > maxDays) return null;

    const days =
      ETHIOPIC_EPOCH_ORDINAL +
      (ethYear - 1) * 365 +
      Math.floor(ethYear / 4) +
      (ethMonth - 1) * 30 +
      (ethDay - 1);

    return ordinalToDate(days);
  }

  function formatEthiopianString(eth) {
    if (!eth) return '';
    const mNameEn = ETHIOPIAN_MONTHS_EN[eth.month - 1] || '';
    const mNameAm = ETHIOPIAN_MONTHS_AM[eth.month - 1] || '';
    return `${eth.day} ${mNameEn} ${eth.year} E.C. (${mNameAm} ${eth.day}, ${eth.year} ዓ.ም.)`;
  }

  function parseEthiopianInput(str) {
    if (!str) return null;
    const clean = str.replace(/E\.C\./gi, '').replace(/EC/gi, '').replace(/ዓ\.ም\./gi, '').trim();

    // 1. Check YYYY-MM-DD or YYYY/MM/DD
    const iso = clean.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/);
    if (iso) {
      return { year: parseInt(iso[1], 10), month: parseInt(iso[2], 10), day: parseInt(iso[3], 10) };
    }

    // 2. Check DD/MM/YYYY or DD-MM-YYYY
    const dmy = clean.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/);
    if (dmy) {
      return { year: parseInt(dmy[3], 10), month: parseInt(dmy[2], 10), day: parseInt(dmy[1], 10) };
    }

    return null;
  }

  function pad(num) {
    return num < 10 ? '0' + num : '' + num;
  }

  function parseGregorianInput(str) {
    if (!str) return null;
    const clean = str.trim();

    // 1. Check DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    const dmy = clean.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/);
    if (dmy) {
      const d = parseInt(dmy[1], 10);
      const m = parseInt(dmy[2], 10);
      const y = parseInt(dmy[3], 10);
      if (m >= 1 && m <= 12 && d >= 1 && d <= 31 && y >= 1) {
        const dim = new Date(Date.UTC(y, m, 0)).getUTCDate();
        if (d <= dim) {
          return { year: y, month: m, day: d };
        }
      }
    }

    // 2. Check YYYY-MM-DD or YYYY/MM/DD
    const ymd = clean.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/);
    if (ymd) {
      const y = parseInt(ymd[1], 10);
      const m = parseInt(ymd[2], 10);
      const d = parseInt(ymd[3], 10);
      if (m >= 1 && m <= 12 && d >= 1 && d <= 31 && y >= 1) {
        const dim = new Date(Date.UTC(y, m, 0)).getUTCDate();
        if (d <= dim) {
          return { year: y, month: m, day: d };
        }
      }
    }

    return null;
  }

  // Bind live two-way synchronization between a Gregorian date input and an Ethiopian date input
  function bindDualDatePicker(gregId, ethId, badgeId) {
    const gregInput = document.getElementById(gregId);
    const ethInput = document.getElementById(ethId);
    if (!gregInput || !ethInput) return;

    // Skip if input uses manual DD/MM/YYYY format — page-level sync handles it
    if (gregInput.getAttribute('data-date-format') === 'dd/mm/yyyy') return;

    let badgeEl = document.getElementById(badgeId);
    if (!badgeEl) {
      badgeEl = document.createElement('div');
      badgeEl.id = badgeId;
      badgeEl.className = 'eth-date-badge mt-1 small text-primary d-flex align-items-center gap-1';
      badgeEl.style.fontSize = '0.78rem';
      ethInput.parentNode.appendChild(badgeEl);
    }

    function isGregInputDmy() {
      return (
        gregInput.getAttribute('data-date-format') === 'dd/mm/yyyy' ||
        gregInput.classList.contains('manual-dmy-date') ||
        (gregInput.type !== 'date' && gregInput.placeholder && gregInput.placeholder.includes('DD/MM/YYYY'))
      );
    }

    function updateFromGregorian() {
      const val = gregInput.value;
      if (!val) {
        badgeEl.innerHTML = '';
        return;
      }
      const greg = parseGregorianInput(val);
      if (greg) {
        const eth = gregorianToEthiopian(greg.year, greg.month, greg.day);
        if (eth) {
          ethInput.value = `${eth.year}-${pad(eth.month)}-${pad(eth.day)}`;
          badgeEl.innerHTML = `<i class="bi bi-calendar2-check text-success"></i> <strong>${formatEthiopianString(eth)}</strong>`;
        }
      }
    }

    function updateFromEthiopian() {
      const val = ethInput.value;
      if (!val) {
        badgeEl.innerHTML = '';
        return;
      }
      const eth = parseEthiopianInput(val);
      if (eth) {
        const greg = ethiopianToGregorian(eth.year, eth.month, eth.day);
        if (greg) {
          if (isGregInputDmy()) {
            gregInput.value = `${pad(greg.day)}/${pad(greg.month)}/${greg.year}`;
          } else {
            gregInput.value = `${greg.year}-${pad(greg.month)}-${pad(greg.day)}`;
          }
          badgeEl.innerHTML = `<i class="bi bi-calendar2-check text-success"></i> <strong>${formatEthiopianString(eth)}</strong>`;
        } else {
          badgeEl.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle"></i> Invalid day for ${ETHIOPIAN_MONTHS_EN[eth.month - 1] || eth.month} ${eth.year}</span>`;
        }
      }
    }

    gregInput.addEventListener('input', updateFromGregorian);
    gregInput.addEventListener('change', updateFromGregorian);
    ethInput.addEventListener('input', updateFromEthiopian);
    ethInput.addEventListener('change', updateFromEthiopian);

    // Initial sync
    if (gregInput.value) {
      updateFromGregorian();
    } else if (ethInput.value) {
      updateFromEthiopian();
    }
  }

  // Initialize on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', function () {
    bindDualDatePicker('id_date', 'id_ethiopian_date', 'eth-date-preview-badge');
    bindDualDatePicker('id_due_date', 'id_ethiopian_due_date', 'eth-due-date-preview-badge');
  });

  // Expose API for external components (like quick filter modals or OCR)
  window.EthiopianCalendar = {
    gregorianToEthiopian: gregorianToEthiopian,
    ethiopianToGregorian: ethiopianToGregorian,
    formatEthiopianString: formatEthiopianString,
    parseEthiopianInput: parseEthiopianInput,
    parseGregorianInput: parseGregorianInput,
    bindDualDatePicker: bindDualDatePicker
  };
})();
