/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\cadastro_senha.js
Último recode: 2026-11-14 06:47:08 (America/Bahia)
Motivo: Atualizar indicadores e confirmação de senha com script próprio e manter a validação sem JavaScript.
*/

(function () {
    "use strict";
    var senha = document.getElementById("senha");
    var confirmar = document.getElementById("confirmar_senha");
    var formulario = document.querySelector(".signup-form");
    if (!senha || !confirmar || !formulario) return;

    function atualizar() {
        var valor = senha.value || "";
        var repeticao = confirmar.value || "";
        var resultado = {
            length: valor.length >= 8,
            case: /[A-Z]/.test(valor) && /[a-z]/.test(valor),
            number: /[0-9]/.test(valor),
            special: /[^A-Za-z0-9]/.test(valor),
            match: valor.length > 0 && valor === repeticao
        };
        Object.keys(resultado).forEach(function (chave) {
            var regra = document.querySelector('[data-password-rule="' + chave + '"]');
            if (regra) regra.classList.toggle("ok", resultado[chave]);
        });
        confirmar.setCustomValidity(repeticao && valor !== repeticao ? "A confirmação de senha não confere." : "");
        return resultado;
    }

    [senha, confirmar].forEach(function (campo) {
        ["input", "change", "keyup", "focus"].forEach(function (evento) {
            campo.addEventListener(evento, atualizar);
        });
    });
    window.addEventListener("pageshow", atualizar);
    formulario.addEventListener("submit", function (evento) {
        atualizar();
        if (!formulario.checkValidity()) {
            evento.preventDefault();
            formulario.reportValidity();
        }
    });
    atualizar();
}());
