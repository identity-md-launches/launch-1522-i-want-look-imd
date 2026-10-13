// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

// These unrestricted sources exist ONLY for local indexer integration tests. Never deploy as applications.
contract SeatTestSource {
    event Transfer(address indexed from, address indexed to, uint256 indexed seat);
    event Activated(uint256 indexed seat, address wallet);
    event Deactivated(uint256 indexed seat);

    function mint(uint256 seat, address wallet) external {
        emit Transfer(address(0), wallet, seat);
    }

    function activate(uint256 seat, address wallet) external {
        emit Activated(seat, wallet);
    }

    function deactivate(uint256 seat) external {
        emit Deactivated(seat);
    }
}

contract TokenTestSource {
    mapping(address => uint256) public balanceOf;
    event Transfer(address indexed from, address indexed to, uint256 amount);

    function mint(address wallet, uint256 amount) external {
        balanceOf[wallet] += amount;
        emit Transfer(address(0), wallet, amount);
    }

    function move(address from, address to, uint256 amount) external {
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}

contract ActivityTestSource {
    TokenTestSource public immutable token;
    event Launched(address indexed wallet, uint256 id);
    event Eligible(address indexed wallet, uint256 allocation, address token, uint256 amount);
    event Claimed(address indexed wallet, uint256 allocation, address token, uint256 amount, address counterparty);
    event Bought(address indexed wallet, address token, uint256 amount, address counterparty);
    event Sold(address indexed wallet, address token, uint256 amount, address counterparty);
    event Interacted(address indexed wallet);

    constructor(address token_) {
        token = TokenTestSource(token_);
    }

    function launch(address wallet, uint256 id) external {
        emit Launched(wallet, id);
    }

    function eligible(address wallet, uint256 allocation, uint256 amount) external {
        emit Eligible(wallet, allocation, address(token), amount);
    }

    function claim(address wallet, uint256 allocation, uint256 amount) external {
        token.move(address(this), wallet, amount);
        emit Claimed(wallet, allocation, address(token), amount, address(this));
    }

    function buy(address wallet, uint256 amount) external {
        token.move(address(this), wallet, amount);
        emit Bought(wallet, address(token), amount, address(this));
    }

    function sell(address wallet, uint256 amount) external {
        token.move(wallet, address(this), amount);
        emit Sold(wallet, address(token), amount, address(this));
    }

    function interact(address wallet) external {
        emit Interacted(wallet);
    }
}
