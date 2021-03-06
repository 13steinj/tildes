$.onmount('[data-js-prevent-double-submit]', function() {
    $(this).on('beforeSend.ic', function(evt, elt, data, settings, xhr, requestId) {
        var $form = $(this);

        if ($form.attr('data-js-submitting') !== undefined) {
            xhr.abort();
            return false;
        } else {
            $form.attr('data-js-submitting', true);
        }
    });

    $(this).on('complete.ic', function() {
        $(this).removeAttr('data-js-submitting');
    });
});
