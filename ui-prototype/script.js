// 사이드바 네비게이션 — 레이아웃 전환만 담당하는 최소 스크립트
(function () {
  const links = document.querySelectorAll(".nav-link");
  const panels = document.querySelectorAll(".panel");

  function activate(targetId) {
    links.forEach((l) =>
      l.classList.toggle("active", l.dataset.target === targetId)
    );
    panels.forEach((p) =>
      p.classList.toggle("active", p.id === targetId)
    );
  }

  links.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      activate(link.dataset.target);
      history.replaceState(null, "", "#" + link.dataset.target);
    });
  });

  // 초기 진입 시 해시 반영
  const initial = (location.hash || "#cctv").slice(1);
  if (document.getElementById(initial)) activate(initial);
})();
