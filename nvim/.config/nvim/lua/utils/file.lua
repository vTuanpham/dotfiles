local M = {}

M.create_file = function()
    local file_name = vim.fn.input('File name: ')
    if file_name == '' then
        vim.notify('File creation cancelled', vim.log.levels.WARN, {
            title = 'File Creation',
            timeout = 2000
        })
        return
    end
    
    local cwd = vim.fn.getcwd()
    local new_file = cwd .. '/' .. file_name
    
    -- Check if file exists
    if vim.fn.filereadable(new_file) == 1 then
        vim.notify('File already exists: ' .. new_file, vim.log.levels.WARN, {
            title = 'File Creation',
            timeout = 2000
        })
        -- Open the existing file
        vim.cmd('edit ' .. vim.fn.fnameescape(new_file))
        return
    end
    
    -- Create directory path if it doesn't exist
    local dir_path = vim.fn.fnamemodify(new_file, ':h')
    if vim.fn.isdirectory(dir_path) == 0 then
        vim.fn.mkdir(dir_path, 'p')
    end
    
    -- Create and open the file
    local file = io.open(new_file, 'w')
    if file then
        file:close()
        vim.notify('Created file: ' .. new_file, vim.log.levels.INFO, {
            title = 'File Creation',
            timeout = 2000,
            icon = '📄'
        })
        -- Open the new file in a buffer
        vim.cmd('edit ' .. vim.fn.fnameescape(new_file))
    else
        vim.notify('Failed to create file: ' .. new_file, vim.log.levels.ERROR, {
            title = 'File Creation',
            timeout = 3000
        })
    end
end

return M
